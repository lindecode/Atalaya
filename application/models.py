from __future__ import annotations

from typing import Any

from ports.clock import Clock
from ports.llm import ModelCatalog
from settings import Settings


MODEL_PREFERENCE = "ollama_model"


class ModelService:
    """Lists the local Ollama models and remembers which one analyze/chat should use (stored in SQLite)."""

    def __init__(self, repository, catalog: ModelCatalog, clock: Clock, settings: Settings):
        self.repository = repository
        self.catalog = catalog
        self.clock = clock
        self.settings = settings

    def current(self) -> str:
        self.repository.initialize()
        return self.repository.get_preference(MODEL_PREFERENCE) or self.settings.ollama_model

    def available(self) -> list[dict[str, Any]]:
        """Raises if Ollama is unreachable; callers decide how to degrade."""
        return self.catalog.list_models()

    def select(self, name: str) -> dict[str, Any]:
        model = next((item for item in self.available() if item["name"] == name), None)
        if model is None:
            raise ValueError(f"El modelo {name!r} no está instalado en Ollama (ollama pull {name})")
        if not model["chat"]:
            raise ValueError(f"{name} es un modelo de embeddings y no puede analizar ni conversar")
        self.repository.initialize()
        self.repository.set_preference(MODEL_PREFERENCE, name, self.clock.now_iso())
        return model
