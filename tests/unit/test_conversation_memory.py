from __future__ import annotations

from dataclasses import replace

from application.conversation_memory import ConversationMemoryService
from infrastructure.sqlite.chat_history import SQLiteChatHistory
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


class Embedder:
    model = "fake-embed"
    def embed(self, texts): return [[float("ssh" in text.casefold()), 1.0] for text in texts]


def test_session_memory_is_chunked_and_scoped(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "memory.db")
    SQLiteRepository(settings).initialize(); history = SQLiteChatHistory(settings)
    first = history.create_session("SSH", "2026-10-05T12:00:00+00:00")
    second = history.create_session("RDP", "2026-10-05T12:00:00+00:00")
    user = history.add_message(first, "2026-10-05T12:00:01+00:00", "user", "revisa el túnel SSH")
    assistant = history.add_message(first, "2026-10-05T12:00:02+00:00", "assistant", "consulta la evidencia 17")
    history.add_message(second, "2026-10-05T12:00:03+00:00", "user", "otro secreto")
    memory = ConversationMemoryService(history, Embedder(), recent_messages=0)
    memory.index_latest_exchange(first, "2026-10-05T12:00:04+00:00")
    context = memory.context(first, "SSH")
    assert "túnel SSH" in context and "otro secreto" not in context
    chunks = history.search_chunks(first, "SSH", [1.0, 1.0])
    assert chunks[0]["first_message_id"] == user and chunks[0]["last_message_id"] == assistant


def test_recent_context_has_a_hard_character_budget(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "memory.db")
    SQLiteRepository(settings).initialize(); history = SQLiteChatHistory(settings)
    session = history.create_session("large", "2026-10-05T12:00:00+00:00")
    history.add_message(session, "2026-10-05T12:00:01+00:00", "user", "x" * 1000)
    assert len(ConversationMemoryService(history, max_chars=200).context(session, "x")) == 200
