from __future__ import annotations

from typing import Any

from settings import Settings


# Fallback for Ollama servers too old to report capabilities in /api/show
EMBEDDING_HINTS = ("embed", "minilm", "bge-", "nomic-bert")


class OllamaModelCatalog:
    """Models installed in the local Ollama, with what each one can do."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def list_models(self) -> list[dict[str, Any]]:
        from ollama import Client

        client = Client(host=self.settings.validated_ollama_host(), timeout=10)
        models = []
        for item in client.list().models:
            name = item.model
            try:
                capabilities = list(client.show(name).capabilities or [])
            except Exception:
                capabilities = []
            if not capabilities:
                capabilities = ["embedding"] if any(hint in name.casefold() for hint in EMBEDDING_HINTS) else ["completion"]
            details = item.details
            models.append({
                "name": name,
                "size_gb": round((item.size or 0) / 1e9, 1),
                "parameters": getattr(details, "parameter_size", None),
                "quantization": getattr(details, "quantization_level", None),
                "capabilities": capabilities,
                "chat": "completion" in capabilities,
                "tools": "tools" in capabilities,
            })
        return sorted(models, key=lambda model: model["name"])
