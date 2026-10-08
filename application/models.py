from __future__ import annotations

from typing import Any

from ports.clock import Clock
from ports.llm import ModelCatalog
from settings import Settings


MODEL_PREFERENCE = "ollama_model"
ROLE_PREFERENCES = {"chat": "ollama_model_chat", "analysis": "ollama_model_analysis", "summary": "ollama_model_summary"}


class ModelService:
    """Lists local-provider models and remembers which one each role should use."""

    def __init__(self, repository, catalog: ModelCatalog, clock: Clock, settings: Settings):
        self.repository = repository
        self.catalog = catalog
        self.clock = clock
        self.settings = settings

    def current(self, role: str = "chat") -> str:
        self.repository.initialize()
        if role not in ROLE_PREFERENCES: raise ValueError(f"Rol de modelo inválido: {role}")
        return (self.repository.get_preference(ROLE_PREFERENCES[role])
                or self.repository.get_preference(MODEL_PREFERENCE) or self.settings.ollama_model)

    def available(self) -> list[dict[str, Any]]:
        """Raises if the selected local provider is unreachable."""
        return self.catalog.list_models()

    def select(self, name: str, role: str = "chat") -> dict[str, Any]:
        model = next((item for item in self.available() if item["name"] == name), None)
        if model is None:
            raise ValueError(f"El modelo {name!r} no está instalado o disponible en el proveedor local")
        if not model["chat"]:
            raise ValueError(f"{name} es un modelo de embeddings y no puede analizar ni conversar")
        self.repository.initialize()
        if role not in ROLE_PREFERENCES: raise ValueError(f"Rol de modelo inválido: {role}")
        self.repository.set_preference(ROLE_PREFERENCES[role], name, self.clock.now_iso())
        return model

    def recommendations(self) -> dict[str, dict[str, Any] | None]:
        models = self.available()
        chat = [model for model in models if model["chat"]]
        tools = [model for model in chat if model["tools"]]
        embeddings = [model for model in models if not model["chat"]]
        size = lambda model: model.get("size_gb") or 0
        return {
            "analysis": max(chat, key=size, default=None),
            "chat": max(tools, key=size, default=None),
            "summary": min(chat, key=size, default=None),
            "embedding": max(embeddings, key=size, default=None),
        }
