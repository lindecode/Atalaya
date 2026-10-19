# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

from infrastructure.sqlite.chat_history import SQLiteChatHistory
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(timezone.utc).isoformat()


def _history(tmp_path, monkeypatch=None):
    database = tmp_path / "chat.db"
    if monkeypatch:
        monkeypatch.setenv("ATALAYA_DB", str(database))
        monkeypatch.setenv("ATALAYA_REPORTS", str(tmp_path / "reports"))
    settings = replace(Settings(), database_path=database, reports_dir=tmp_path / "reports")
    SQLiteRepository(settings).initialize()
    return SQLiteChatHistory(settings)


def test_archived_conversations_leave_the_list_without_being_deleted(tmp_path):
    history = _history(tmp_path)
    keep, archive = history.create_session("activa", NOW), history.create_session("vieja", NOW)
    history.add_message(archive, NOW, "user", "hola")
    assert history.set_archived(archive, True, NOW)
    assert [row["id"] for row in history.list_sessions()] == [keep]
    assert [row["id"] for row in history.list_sessions(archived=True)] == [archive]
    assert history.list_sessions("hola", archived=True)[0]["messages"] == 1  # search works on archived too
    assert history.get_session(archive)["messages"]                           # nothing was deleted

    history.add_message(archive, NOW, "user", "sigo aquí")  # writing again restores it
    assert {row["id"] for row in history.list_sessions()} == {keep, archive}


def test_archive_and_restore_from_the_chat_page(tmp_path, monkeypatch):
    history = _history(tmp_path, monkeypatch)
    session = history.create_session("para archivar", NOW)
    history.add_message(session, NOW, "user", "pregunta")
    app = AppTest.from_file(ROOT / "interfaces/gui/views/21_Chat.py", default_timeout=30).run()
    app.button(key=f"chat-session-{session}").click().run()
    app.button(key="chat-archive").click().run()
    assert not app.exception
    assert not any(button.key == f"chat-session-{session}" for button in app.button)

    app.toggle(key="chat-archived").set_value(True).run()
    app.button(key=f"chat-session-{session}").click().run()
    app.button(key="chat-unarchive").click().run()
    assert not app.exception
    assert history.list_sessions()[0]["id"] == session


def test_a_suggestion_is_sent_as_the_question(tmp_path, monkeypatch):
    _history(tmp_path, monkeypatch)
    asked = []

    class FakeChat:
        def ask(self, question, session_id=None, **_):
            asked.append(question)
            return {"session_id": None}

    import bootstrap
    monkeypatch.setattr(bootstrap, "build_recorded_chat_service", lambda *args, **kwargs: FakeChat())
    app = AppTest.from_file(ROOT / "interfaces/gui/views/21_Chat.py", default_timeout=30).run()
    suggestions = [button for button in app.button if button.key and button.key.startswith("chat-suggest-")]
    assert len(suggestions) >= 6
    suggestions[0].click().run()
    assert not app.exception
    assert asked == [suggestions[0].label]
