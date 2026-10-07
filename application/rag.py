from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import replace
from pathlib import Path

from application.chunking import MarkdownChunker
from domain.knowledge import RetrievedChunk


class RagService:
    def __init__(self, store, clock, settings, embedder=None):
        self.store, self.clock, self.settings, self.embedder = store, clock, settings, embedder
        self.chunker = MarkdownChunker(settings.rag_chunk_chars, settings.rag_chunk_overlap_chars)

    def _safe_path(self, value: Path) -> Path:
        candidate = value if value.is_absolute() else (Path.cwd() / value)
        if candidate.is_symlink(): raise ValueError(f"No se permiten enlaces simbólicos: {value}")
        path = candidate.resolve()
        root = self.settings.project_dir.resolve()
        if path.suffix.casefold() != ".md" or root not in path.parents:
            raise ValueError(f"Solo se permiten Markdown dentro del proyecto: {value}")
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f"Documento demasiado grande: {value}")
        return path

    def default_sources(self) -> list[Path]:
        """Project documentation wherever it lives: README/*.md and root README*.md.

        agente.md is left out on purpose: it is the original development plan, outdated in places, and the
        chat would cite it as trusted knowledge. It can still be indexed explicitly with `rag index agente.md`.
        """
        root = self.settings.project_dir
        found = sorted((root / "README").glob("*.md")) + sorted(root.glob("README*.md"))
        return [path for path in found if path.is_file()]

    def index(self, paths: list[Path] | None = None):
        self.store.initialize()
        prune = not paths
        if paths:
            missing = [str(path) for path in paths if not path.exists()]
            if missing:
                raise ValueError(f"No existe: {', '.join(missing)}")
        else:
            paths = self.default_sources()
            if not paths:
                raise ValueError(f"No hay documentación Markdown que indexar en {self.settings.project_dir}")
        totals = {"sources": 0, "chunks": 0, "embedded": 0, "embedding_error": None, "removed_sources": []}
        indexed: list[str] = []
        for raw_path in paths:
            path = self._safe_path(raw_path)
            relative = path.relative_to(self.settings.project_dir).as_posix()
            chunks = self.chunker.chunk(Path(relative), path.read_text(encoding="utf-8"), "trusted")
            vectors = [None] * len(chunks)
            if self.embedder:
                cached = self.store.cached_embeddings(relative, self.embedder.model)
                missing_indexes = [i for i, chunk in enumerate(chunks) if chunk.content_hash not in cached]
                try:
                    missing_vectors = self.embedder.embed([chunks[i].content for i in missing_indexes]) if missing_indexes else []
                    for index, vector in zip(missing_indexes, missing_vectors): vectors[index] = vector
                    for index, chunk in enumerate(chunks):
                        if vectors[index] is None: vectors[index] = cached.get(chunk.content_hash)
                except Exception as exc:
                    totals["embedding_error"] = f"{type(exc).__name__}: {exc}"
                    vectors = [cached.get(chunk.content_hash) for chunk in chunks]
            result = self.store.replace_source(relative, chunks, vectors, self.embedder.model if self.embedder else None,
                                               self.clock.now_iso())
            totals["sources"] += 1; totals["chunks"] += result["total"]
            totals["embedded"] += sum(vector is not None for vector in vectors)
            indexed.append(relative)
        if prune:
            # A full re-index drops documents that were moved or deleted, so the chat cannot cite stale paths
            totals["removed_sources"] = self.store.remove_sources_except(indexed)
        return totals

    def search(self, query: str, top_k: int | None = None, trust_levels=("trusted",)):
        self.store.initialize()
        query = " ".join(query.replace("\x00", " ").split())[:1000]
        if not query: raise ValueError("Consulta vacía")
        top_k = min(max(top_k or self.settings.rag_top_k, 1), 20)
        started = time.perf_counter()
        lexical = self.store.lexical_search(query, trust_levels, limit=max(top_k * 4, 20))
        scores = {item.id: item.score * 0.40 for item in lexical}
        chunks = {item.id: item for item in lexical}
        route, embedding_model = "lexical", None
        if self.embedder:
            try:
                query_vector = self.embedder.embed([query])[0]
                embedding_model = self.embedder.model; route = "hybrid"
                for item, vector in self.store.vector_candidates(trust_levels):
                    chunks[item.id] = item
                    scores[item.id] = scores.get(item.id, 0.0) + 0.25 * _cosine(query_vector, vector)
            except Exception:
                route = "lexical_fallback"
        query_terms = _search_terms(query)
        for item_id, item in chunks.items():
            haystack = f"{item.title} {item.section} {item.content}".casefold()
            matched = sum(term in haystack for term in query_terms)
            coverage = matched / len(query_terms) if query_terms else 0.0
            scores[item_id] = scores.get(item_id, 0.0) + 0.25 * coverage + _source_priority(item.source_uri)
        ranked = [replace(chunks[item_id], score=score) for item_id, score in scores.items()]
        ranked.sort(key=lambda item: item.score, reverse=True)
        result = ranked[:top_k]
        elapsed = int((time.perf_counter() - started) * 1000)
        self.store.audit_rag(self.clock.now_iso(), hashlib.sha256(query.encode()).hexdigest(), route,
                             [item.id for item in result], embedding_model, elapsed)
        return result

    def as_tool_rows(self, query: str, top_k: int | None = None):
        rows, used = [], 0
        for item in self.search(query, top_k, ("trusted", "derived")):
            remaining = self.settings.rag_max_context_chars - used
            if remaining <= 0: break
            content = item.content[:min(4000, remaining)]
            rows.append({"id": f"K:{item.id}", "citation": f"[K:{item.id}]", "source": item.source_uri,
                         "section": item.section, "trust_level": item.trust_level, "score": round(item.score, 4),
                         "content": content})
            used += len(content)
        return rows

    def status(self):
        self.store.initialize(); return self.store.knowledge_status()


def _cosine(left, right):
    if len(left) != len(right) or not left: return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


def _search_terms(query: str) -> set[str]:
    stopwords = {"como", "cómo", "para", "por", "una", "uno", "con", "del", "las", "los", "que", "qué", "un", "el", "la"}
    return {token for token in re.findall(r"[\w.-]+", query.casefold()) if len(token) > 2 and token not in stopwords}


def _source_priority(source_uri: str) -> float:
    name = Path(source_uri).name.casefold()
    return {"readme.man.md": 0.10, "readme.md": 0.05}.get(name, 0.0)
