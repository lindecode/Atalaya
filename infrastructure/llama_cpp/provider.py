from __future__ import annotations

from pathlib import Path

from infrastructure.llama_cpp.client import LlamaCppClient
from infrastructure.llama_cpp.credentials import load_or_create_key
from infrastructure.llama_cpp.endpoints import runtime_host
from infrastructure.ollama.analyzer import OllamaAnalyzer


class LlamaCppAnalyzer(OllamaAnalyzer):
    """Reuses Atalaya's validated analysis schema with the llama.cpp transport."""

    def __init__(self, settings):
        from infrastructure.llm_provider import effective_settings
        settings = effective_settings(settings)
        super().__init__(settings)
        self.model = _model_name(settings.llama_cpp_model_path)

    def _client(self):
        return LlamaCppClient(runtime_host(self.settings, "chat"), self.settings.llm_timeout_seconds,
                              load_or_create_key(self.settings, "chat"))


class LlamaCppEmbeddingProvider:
    def __init__(self, settings, model: str | None = None, client=None):
        from infrastructure.llm_provider import effective_settings
        settings = effective_settings(settings)
        self.settings = settings
        self.model = model or _model_name(settings.llama_cpp_embedding_model_path)
        self.client = client

    def embed(self, texts):
        if not texts:
            return []
        if self.client is None:
            from infrastructure.llama_cpp.runtime import ensure_running
            ensure_running(self.settings, role="embedding")
            self.client = LlamaCppClient(runtime_host(self.settings, "embedding"),
                                         self.settings.llm_timeout_seconds,
                                         load_or_create_key(self.settings, "embedding"))
        response = self.client.embed(model=self.model, input=list(texts))
        if not response.embeddings or len(response.embeddings) != len(texts):
            raise ValueError("llama-server devolvió embeddings incompletos")
        return [list(map(float, vector)) for vector in response.embeddings]


class LlamaCppModelCatalog:
    def __init__(self, settings):
        from infrastructure.llm_provider import effective_settings
        self.settings = effective_settings(settings)

    def list_models(self):
        client = LlamaCppClient(runtime_host(self.settings, "chat"), 10,
                                load_or_create_key(self.settings, "chat"))
        models = client.list_models()
        size = self.settings.llama_cpp_model_path.stat().st_size if self.settings.llama_cpp_model_path.exists() else 0
        return [{"name": _model_name(self.settings.llama_cpp_model_path),
                 "size_gb": round(size / 1e9, 1), "parameters": None, "quantization": None,
                 "capabilities": ["completion", "tools", "embedding"], "chat": True, "tools": True}
                for item in models]


def _model_name(path: Path) -> str:
    return path.stem or "atalaya"
