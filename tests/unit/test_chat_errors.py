from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

from application.chat import ChatService
from infrastructure.sqlite.chat_tools import SQLiteQueryTools
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


def test_chat_reports_bad_tool_arguments_to_the_model(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "t.db")
    SQLiteRepository(settings).initialize()

    class Client:
        calls = 0
        def chat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                function = SimpleNamespace(name="get_alerts", arguments={"since": "la semana pasada"})
                return SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[SimpleNamespace(function=function)]))
            assert "error" in json.loads(kwargs["messages"][-1]["content"])
            return SimpleNamespace(message=SimpleNamespace(content="No pude filtrar por esa fecha.", tool_calls=[]))

    result = ChatService(settings, SQLiteQueryTools(settings), Client()).ask("alertas de la semana pasada")
    assert result["tool_calls"][0]["error"]
    assert result["answer"]
