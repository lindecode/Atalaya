from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from application.models import ModelService
from infrastructure.ollama.client import ThinkFallbackClient, chat
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


class Clock:
    def now_iso(self): return datetime.now(timezone.utc).isoformat()


class Catalog:
    def list_models(self):
        return [{"name": "qwen3.5:4b", "chat": True, "tools": True},
                {"name": "granite4.1:3b", "chat": True, "tools": True},
                {"name": "all-minilm:latest", "chat": False, "tools": False}]


def test_model_selection_is_persisted_and_validated(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "t.db")
    repository = SQLiteRepository(settings)
    service = ModelService(repository, Catalog(), Clock(), settings)
    assert service.current() == settings.ollama_model
    service.select("granite4.1:3b")
    assert ModelService(repository, Catalog(), Clock(), settings).current() == "granite4.1:3b"
    with pytest.raises(ValueError, match="embeddings"):
        service.select("all-minilm:latest")
    with pytest.raises(ValueError, match="no está instalado"):
        service.select("llama9:70b")


def test_think_flag_is_dropped_for_models_without_thinking():
    class Client:
        calls = []
        def chat(self, **kwargs):
            self.calls.append(kwargs)
            if "think" in kwargs:
                raise RuntimeError('"granite4.1:3b" does not support thinking')
            return "ok"
    client = Client()
    assert chat(client, model="granite4.1:3b", think=False) == "ok"
    assert "think" not in client.calls[-1]


def test_injected_chat_client_applies_the_think_fallback():
    class Client:
        def chat(self, **kwargs):
            if "think" in kwargs:
                raise RuntimeError("model does not support thinking")
            return kwargs
    assert ThinkFallbackClient(Client()).chat(model="granite4.1:3b", think=False) == {"model": "granite4.1:3b"}
