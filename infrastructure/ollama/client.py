from __future__ import annotations

from typing import Any


def chat(client, **kwargs: Any):
    """client.chat with think=False, retried without it for models that have no thinking mode (e.g. granite)."""
    try:
        return client.chat(**kwargs)
    except Exception as exc:
        if "think" in kwargs and "thinking" in str(exc).casefold():
            kwargs.pop("think")
            return client.chat(**kwargs)
        raise


class ThinkFallbackClient:
    """Ollama client whose chat() applies the same fallback; what bootstrap injects into ChatService."""

    def __init__(self, client):
        self.client = client

    def chat(self, **kwargs: Any):
        return chat(self.client, **kwargs)


def build_chat_client(settings) -> ThinkFallbackClient:
    from ollama import Client
    return ThinkFallbackClient(Client(host=settings.validated_ollama_host(), timeout=settings.llm_timeout_seconds))


def pull_model(settings, name: str):
    """Downloads a model through the local Ollama; yields (status, completed, total)."""
    from ollama import Client
    client = Client(host=settings.validated_ollama_host())
    for progress in client.pull(name, stream=True):
        yield progress.status or "", progress.completed or 0, progress.total or 0
