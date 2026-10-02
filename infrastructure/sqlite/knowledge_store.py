from __future__ import annotations

import json
import math
import re
from typing import Any

from domain.knowledge import KnowledgeChunk, RetrievedChunk
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.migrations import MIGRATIONS


TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
STOPWORDS = {"como", "cómo", "para", "por", "una", "uno", "unos", "unas", "con", "del", "las", "los", "que", "qué", "esta", "este"}


class SQLiteKnowledgeStore:
    def __init__(self, settings): self.settings = settings

    def _connect(self, readonly=False):
        return connect(self.settings.database_path, self.settings.sqlite_busy_timeout_ms, readonly)

    def initialize(self):
        self.settings.ensure_runtime_dirs()
        with self._connect() as db:
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            for index, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                db.executescript(sql); db.execute(f"PRAGMA user_version={index}")

    def cached_embeddings(self, source_uri: str, embedding_model: str) -> dict[str, list[float]]:
        with self._connect(readonly=True) as db:
            rows = db.execute(
                "SELECT content_hash, embedding_json FROM knowledge_chunks WHERE source_uri=? AND embedding_model=? AND embedding_json IS NOT NULL",
                (source_uri, embedding_model),
            )
            return {row[0]: json.loads(row[1]) for row in rows}

    def replace_source(self, source_uri: str, chunks: list[KnowledgeChunk], embeddings, embedding_model, ts: str):
        embeddings = embeddings or [None] * len(chunks)
        if len(embeddings) != len(chunks): raise ValueError("Chunks y embeddings no coinciden")
        inserted = updated = 0
        keys = {chunk.chunk_key for chunk in chunks}
        with self._connect() as db:
            existing_ids = [row[0] for row in db.execute("SELECT id FROM knowledge_chunks WHERE source_uri=?", (source_uri,))]
            if existing_ids:
                placeholders = ",".join("?" for _ in existing_ids)
                db.execute(f"DELETE FROM knowledge_fts WHERE chunk_id IN ({placeholders})", existing_ids)
            if keys:
                placeholders = ",".join("?" for _ in keys)
                db.execute(f"DELETE FROM knowledge_chunks WHERE source_uri=? AND chunk_key NOT IN ({placeholders})", (source_uri, *keys))
            else:
                db.execute("DELETE FROM knowledge_chunks WHERE source_uri=?", (source_uri,))
            for chunk, vector in zip(chunks, embeddings):
                exists = db.execute("SELECT id, content_hash FROM knowledge_chunks WHERE chunk_key=?", (chunk.chunk_key,)).fetchone()
                db.execute(
                    """INSERT INTO knowledge_chunks
                    (chunk_key,source_uri,title,section,content,trust_level,content_hash,embedding_model,embedding_json,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(chunk_key) DO UPDATE SET title=excluded.title,section=excluded.section,
                      content=excluded.content,trust_level=excluded.trust_level,content_hash=excluded.content_hash,
                      embedding_model=excluded.embedding_model,embedding_json=excluded.embedding_json,updated_at=excluded.updated_at""",
                    (chunk.chunk_key, chunk.source_uri, chunk.title, chunk.section, chunk.content, chunk.trust_level,
                     chunk.content_hash, embedding_model if vector is not None else None,
                     json.dumps(vector) if vector is not None else None, ts),
                )
                row_id = int(db.execute("SELECT id FROM knowledge_chunks WHERE chunk_key=?", (chunk.chunk_key,)).fetchone()[0])
                db.execute("INSERT INTO knowledge_fts(chunk_id,title,section,content) VALUES (?,?,?,?)",
                           (row_id, chunk.title, chunk.section, chunk.content))
                if exists: updated += 1
                else: inserted += 1
        return {"inserted": inserted, "updated": updated, "total": len(chunks)}

    def remove_sources_except(self, keep: list[str]) -> list[str]:
        """Delete every indexed source not in `keep`; returns the removed source URIs."""
        with self._connect() as db:
            stale = [row[0] for row in db.execute("SELECT DISTINCT source_uri FROM knowledge_chunks")
                     if row[0] not in set(keep)]
            for source_uri in stale:
                db.execute("DELETE FROM knowledge_fts WHERE chunk_id IN (SELECT id FROM knowledge_chunks WHERE source_uri=?)", (source_uri,))
                db.execute("DELETE FROM knowledge_chunks WHERE source_uri=?", (source_uri,))
        return stale

    @staticmethod
    def _trust_sql(trust_levels):
        if not trust_levels: raise ValueError("Se requiere al menos un nivel de confianza")
        if any(value not in {"trusted", "derived", "untrusted", "llm_generated"} for value in trust_levels):
            raise ValueError("Nivel de confianza inválido")
        return ",".join("?" for _ in trust_levels)

    def lexical_search(self, query: str, trust_levels=("trusted",), limit=20):
        tokens = [token for token in TOKEN.findall(query.casefold()) if len(token) >= 3 and token not in STOPWORDS][:20]
        if not tokens: return []
        expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        trust_sql = self._trust_sql(trust_levels)
        with self._connect(readonly=True) as db:
            rows = db.execute(
                f"""SELECT k.*, bm25(knowledge_fts) rank FROM knowledge_fts
                JOIN knowledge_chunks k ON k.id=knowledge_fts.chunk_id
                WHERE knowledge_fts MATCH ? AND k.trust_level IN ({trust_sql}) ORDER BY rank LIMIT ?""",
                (expression, *trust_levels, min(limit, 100)),
            )
            return [RetrievedChunk(int(row["id"]), row["source_uri"], row["title"], row["section"], row["content"],
                                   row["trust_level"], 1.0 / rank) for rank, row in enumerate(rows, start=1)]

    def vector_candidates(self, trust_levels=("trusted",), limit=2000):
        trust_sql = self._trust_sql(trust_levels)
        with self._connect(readonly=True) as db:
            rows = db.execute(
                f"SELECT * FROM knowledge_chunks WHERE embedding_json IS NOT NULL AND trust_level IN ({trust_sql}) LIMIT ?",
                (*trust_levels, min(limit, 2000)),
            )
            return [(RetrievedChunk(int(row["id"]), row["source_uri"], row["title"], row["section"], row["content"],
                                    row["trust_level"], 0.0), json.loads(row["embedding_json"])) for row in rows]

    def audit_rag(self, ts, query_hash, route, ids, embedding_model, duration_ms):
        with self._connect() as db:
            db.execute("INSERT INTO rag_audit(ts,query_hash,route,retrieved_ids,embedding_model,duration_ms) VALUES (?,?,?,?,?,?)",
                       (ts, query_hash, route, json.dumps(ids), embedding_model, duration_ms))

    def knowledge_status(self):
        with self._connect(readonly=True) as db:
            total = int(db.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0])
            embedded = int(db.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE embedding_json IS NOT NULL").fetchone()[0])
            sources = [dict(row) for row in db.execute("SELECT source_uri,trust_level,COUNT(*) chunks,MAX(updated_at) updated_at FROM knowledge_chunks GROUP BY source_uri,trust_level")]
            audits = int(db.execute("SELECT COUNT(*) FROM rag_audit").fetchone()[0])
        return {"chunks": total, "embedded": embedded, "sources": sources, "queries_audited": audits}
