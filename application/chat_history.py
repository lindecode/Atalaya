from __future__ import annotations

import time
from typing import Any


TITLE_CHARS = 70


class RecordedChatService:
    """Asks the chat and keeps every question, answer and error in the local history.

    Each question is still answered on its own (no earlier turns are sent to the model): a conversation
    groups related questions for later review, it does not carry context, so an old answer cannot steer
    a new one.
    """

    def __init__(self, chat, history, clock, model: str):
        self.chat, self.history, self.clock, self.model = chat, history, clock, model

    def ask(self, question: str, session_id: int | None = None) -> dict[str, Any]:
        question = " ".join(question.split())
        if not question:
            raise ValueError("Pregunta vacía")
        if session_id is None:
            title = question[:TITLE_CHARS] + ("…" if len(question) > TITLE_CHARS else "")
            session_id = self.history.create_session(title, self.clock.now_iso())
        self.history.add_message(session_id, self.clock.now_iso(), "user", question)
        started = time.perf_counter()
        try:
            result = self.chat.ask(question)
        except Exception as exc:
            self.history.add_message(session_id, self.clock.now_iso(), "error", f"{type(exc).__name__}: {exc}", self.model,
                                     duration_ms=int((time.perf_counter() - started) * 1000))
            exc.session_id = session_id  # lets the caller open the conversation where the error was stored
            raise
        self.history.add_message(session_id, self.clock.now_iso(), "assistant", result["answer"], self.model,
                                 result["tool_calls"], int((time.perf_counter() - started) * 1000))
        return {**result, "session_id": session_id}
