from __future__ import annotations

from dataclasses import replace

import pytest

from application.chat_history import RecordedChatService
from infrastructure.sqlite.chat_history import SQLiteChatHistory
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


class Clock:
    def __init__(self): self.tick = 0
    def now_iso(self):
        self.tick += 1
        return f"2026-10-02T12:00:{self.tick:02d}+00:00"


class FakeChat:
    def __init__(self, fail=False): self.fail, self.questions = fail, []
    def ask(self, question):
        self.questions.append(question)
        if self.fail:
            raise ConnectionError("Ollama apagado")
        return {"answer": f"respuesta a: {question}", "tool_calls": [{"name": "get_alerts", "arguments": {}, "ids": [3]}]}


def _history(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "chat.db")
    SQLiteRepository(settings).initialize()
    return SQLiteChatHistory(settings)


def test_conversation_is_saved_and_can_be_continued(tmp_path):
    history = _history(tmp_path)
    service = RecordedChatService(FakeChat(), history, Clock(), "qwen3.5:4b")

    first = service.ask("¿Quién se conectó por RDP?")
    second = service.ask("¿Y por SMB?", first["session_id"])

    assert second["session_id"] == first["session_id"]
    session = history.get_session(first["session_id"])
    assert session["title"] == "¿Quién se conectó por RDP?"
    assert [m["role"] for m in session["messages"]] == ["user", "assistant", "user", "assistant"]
    assert session["messages"][1]["model"] == "qwen3.5:4b"
    assert session["messages"][1]["tool_calls"][0]["ids"] == [3]
    assert history.list_sessions()[0]["messages"] == 4


def test_each_question_is_answered_without_earlier_turns(tmp_path):
    chat = FakeChat()
    service = RecordedChatService(chat, _history(tmp_path), Clock(), "m")
    session = service.ask("primera")["session_id"]
    service.ask("segunda", session)
    assert chat.questions == ["primera", "segunda"]  # an old answer never reaches the model again


def test_failures_are_recorded_in_the_conversation(tmp_path):
    history = _history(tmp_path)
    service = RecordedChatService(FakeChat(fail=True), history, Clock(), "m")
    with pytest.raises(ConnectionError) as raised:
        service.ask("¿hay alertas?")
    session = history.get_session(raised.value.session_id)
    assert [m["role"] for m in session["messages"]] == ["user", "error"]
    assert "Ollama apagado" in session["messages"][1]["content"]


def test_search_titles_and_messages_with_literal_wildcards(tmp_path):
    history = _history(tmp_path)
    service = RecordedChatService(FakeChat(), history, Clock(), "m")
    rdp = service.ask("conexiones RDP")["session_id"]
    service.ask("uso de 100% CPU")
    assert [s["id"] for s in history.list_sessions("respuesta a: conexiones")] == [rdp]   # matches an answer
    assert len(history.list_sessions("100%")) == 1 and history.list_sessions("_") == []    # % and _ are literal


def test_long_titles_are_cut_and_empty_questions_rejected(tmp_path):
    service = RecordedChatService(FakeChat(), _history(tmp_path), Clock(), "m")
    long_id = service.ask("x" * 200)["session_id"]
    assert service.history.get_session(long_id)["title"].endswith("…")
    with pytest.raises(ValueError):
        service.ask("   ")


def test_export_and_delete(tmp_path):
    history = _history(tmp_path)
    service = RecordedChatService(FakeChat(), history, Clock(), "m")
    session = service.ask("respuesta con ``` dentro")["session_id"]
    markdown = history.export_markdown(session)
    assert "````text" in markdown and "get_alerts ids=[3]" in markdown  # fence longer than the backticks inside
    assert history.delete_session(session) and history.get_session(session) is None
    assert not history.delete_session(session)
    with pytest.raises(KeyError):
        history.add_message(session, "2026-10-02T12:00:00+00:00", "user", "x")
