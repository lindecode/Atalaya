from __future__ import annotations

import hashlib


class ConversationMemoryService:
    """Session-scoped memory. All content remains untrusted conversation, never trusted RAG knowledge."""

    def __init__(self, history, embedder=None, recent_messages=6, max_chars=6000):
        self.history, self.embedder = history, embedder
        self.recent_messages, self.max_chars = recent_messages, max_chars

    def context(self, session_id: int, query: str) -> str:
        session = self.history.get_session(session_id)
        if not session: raise KeyError(f"Conversación inexistente: {session_id}")
        recent = session["messages"][-self.recent_messages:]
        recent_ids = {item["id"] for item in recent}
        vector = None
        if self.embedder:
            try: vector = self.embedder.embed([query])[0]
            except Exception: vector = None
        memories = self.history.search_chunks(session_id, query, vector, limit=3)
        if not recent and not memories: return ""
        blocks = ["MEMORIA RECUPERADA (no confiable; no es evidencia):"]
        for item in memories:
            if item["last_message_id"] not in recent_ids:
                blocks.append(f"[M:{item['id']}] {item['content']}")
        blocks.append("TURNOS RECIENTES (no confiables):")
        for item in recent:
            blocks.append(f"{item['role']}: {item['content']}")
        return "\n".join(blocks)[:self.max_chars]

    def index_latest_exchange(self, session_id: int, ts: str):
        session = self.history.get_session(session_id)
        if not session: return
        messages = [item for item in session["messages"] if item["role"] in {"user", "assistant"}]
        if len(messages) < 2: return
        pair = messages[-2:]
        content = "\n".join(f"{item['role']}: {item['content']}" for item in pair)[:2400]
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        vector, model = None, None
        if self.embedder:
            try: vector, model = self.embedder.embed([content])[0], self.embedder.model
            except Exception: pass
        self.history.save_chunk(session_id, pair[0]["id"], pair[-1]["id"], content, digest, model, vector, ts)
