from __future__ import annotations

import json
import math
import re
from typing import Any

from infrastructure.sqlite.connection import connect


class SQLiteChatHistory:
    """Chat conversations kept in the local database so they can be reviewed later."""

    def __init__(self, settings):
        self.settings = settings

    def _connect(self, readonly: bool = False):
        return connect(self.settings.database_path, self.settings.sqlite_busy_timeout_ms, readonly)

    def create_session(self, title: str, ts: str) -> int:
        with self._connect() as db:
            cursor = db.execute("INSERT INTO chat_sessions(title, created_at, updated_at) VALUES (?, ?, ?)", (title, ts, ts))
            return int(cursor.lastrowid)

    def add_message(self, session_id: int, ts: str, role: str, content: str, model: str | None = None,
                    tool_calls: list[dict[str, Any]] | None = None, duration_ms: int | None = None) -> int:
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM chat_sessions WHERE id=?", (session_id,)).fetchone():
                raise KeyError(f"Conversación inexistente: {session_id}")
            cursor = db.execute(
                """INSERT INTO chat_messages(session_id, ts, role, content, model, tool_calls_json, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, ts, role, content, model,
                 json.dumps(tool_calls, ensure_ascii=False, default=str) if tool_calls is not None else None, duration_ms),
            )
            db.execute("UPDATE chat_sessions SET updated_at=? WHERE id=?", (ts, session_id))
            return int(cursor.lastrowid)

    def list_sessions(self, search: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = """SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(m.id) messages
                 FROM chat_sessions s LEFT JOIN chat_messages m ON m.session_id = s.id"""
        params: list[Any] = []
        if search:
            # Match the title or any message of the conversation
            sql += """ WHERE s.title LIKE ? ESCAPE '\\' OR s.id IN
                       (SELECT session_id FROM chat_messages WHERE content LIKE ? ESCAPE '\\')"""
            pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params += [pattern, pattern]
        sql += " GROUP BY s.id ORDER BY s.updated_at DESC LIMIT ?"
        params.append(min(max(int(limit), 1), 1000))
        with self._connect(readonly=True) as db:
            return [dict(row) for row in db.execute(sql, params)]

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        with self._connect(readonly=True) as db:
            session = db.execute("SELECT * FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
            if not session:
                return None
            messages = [dict(row) for row in db.execute(
                "SELECT * FROM chat_messages WHERE session_id=? ORDER BY id", (session_id,))]
        for message in messages:
            message["tool_calls"] = json.loads(message.pop("tool_calls_json") or "null")
        return {**dict(session), "messages": messages}

    def delete_session(self, session_id: int) -> bool:
        with self._connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM conversation_chunks WHERE session_id=?", (session_id,))]
            db.executemany("DELETE FROM conversation_chunks_fts WHERE chunk_id=?", ((value,) for value in ids))
            db.execute("DELETE FROM conversation_chunks WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
            return db.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,)).rowcount == 1

    def export_markdown(self, session_id: int) -> str:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Conversación inexistente: {session_id}")
        names = {"user": "Pregunta", "assistant": "Respuesta", "error": "Error"}
        lines = [f"# {session['title']}", "", f"Conversación #{session['id']} · creada {session['created_at']}", ""]
        for message in session["messages"]:
            model = f" · {message['model']}" if message.get("model") else ""
            # A fence longer than any backtick run in the text, so a reply cannot close it early
            fence = "`" * max(3, max((len(run) for run in re.findall(r"`+", message["content"])), default=0) + 1)
            lines += [f"## {names[message['role']]} · {message['ts']}{model}", "", f"{fence}text", message["content"], fence, ""]
            if message.get("tool_calls"):
                calls = ", ".join(f"{call['name']} ids={call.get('ids', [])}" for call in message["tool_calls"])
                lines += [f"Herramientas: {calls}", ""]
        return "\n".join(lines)

    def save_chunk(self, session_id, first_id, last_id, content, content_hash, embedding_model, vector, ts):
        with self._connect() as db:
            existing = db.execute("SELECT id FROM conversation_chunks WHERE session_id=? AND first_message_id=? AND last_message_id=?",
                                  (session_id, first_id, last_id)).fetchone()
            if existing: return int(existing[0])
            cursor = db.execute("""INSERT INTO conversation_chunks
                (session_id,first_message_id,last_message_id,content,content_hash,embedding_model,embedding_json,created_at)
                VALUES (?,?,?,?,?,?,?,?)""", (session_id, first_id, last_id, content, content_hash, embedding_model,
                                               json.dumps(vector) if vector is not None else None, ts))
            chunk_id = int(cursor.lastrowid)
            db.execute("INSERT INTO conversation_chunks_fts(chunk_id,content) VALUES (?,?)", (chunk_id, content))
            return chunk_id

    def search_chunks(self, session_id, query, query_vector=None, limit=3):
        tokens = re.findall(r"[\w.-]+", query.casefold())[:12]
        scores = {}
        with self._connect(readonly=True) as db:
            if tokens:
                expression = " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)
                rows = db.execute("""SELECT c.*, bm25(conversation_chunks_fts) rank FROM conversation_chunks_fts f
                    JOIN conversation_chunks c ON c.id=f.chunk_id WHERE c.session_id=? AND conversation_chunks_fts MATCH ? LIMIT 20""",
                                  (session_id, expression)).fetchall()
                for rank, row in enumerate(rows): scores[row["id"]] = (dict(row), 1 / (rank + 1))
            if query_vector:
                for row in db.execute("SELECT * FROM conversation_chunks WHERE session_id=? AND embedding_json IS NOT NULL", (session_id,)):
                    vector = json.loads(row["embedding_json"]); denominator = math.sqrt(sum(x*x for x in query_vector)) * math.sqrt(sum(x*x for x in vector))
                    cosine = sum(a*b for a, b in zip(query_vector, vector)) / denominator if denominator and len(vector) == len(query_vector) else 0
                    previous = scores.get(row["id"], (dict(row), 0))[1]
                    scores[row["id"]] = (dict(row), previous * .6 + cosine * .4)
        return [item for item, _ in sorted(scores.values(), key=lambda value: value[1], reverse=True)[:limit]]
