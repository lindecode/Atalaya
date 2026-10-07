from __future__ import annotations

from pathlib import Path

from infrastructure.llama_cpp.client import LlamaCppClient
from infrastructure.ollama.analyzer import OllamaAnalyzer


class LlamaCppAnalyzer(OllamaAnalyzer):
    """Reuses Atalaya's validated analysis schema with the llama.cpp transport."""

    def __init__(self, settings):
        super().__init__(settings)
        self.model = _model_name(settings.llama_cpp_model_path)

    def _client(self):
        return LlamaCppClient(self.settings.validated_llama_cpp_host(), self.settings.llm_timeout_seconds)


class LlamaCppEmbeddingProvider:
    def __init__(self, settings, model: str | None = None, client=None):
        self.model = model or _model_name(settings.llama_cpp_model_path)
        self.client = client or LlamaCppClient(settings.validated_llama_cpp_host(), settings.llm_timeout_seconds)

    def embed(self, texts):
        if not texts:
            return []
        response = self.client.embed(model=self.model, input=list(texts))
        if not response.embeddings or len(response.embeddings) != len(texts):
            raise ValueError("llama-server devolvió embeddings incompletos")
        return [list(map(float, vector)) for vector in response.embeddings]


class LlamaCppModelCatalog:
    def __init__(self, settings):
        self.settings = settings

    def list_models(self):
        client = LlamaCppClient(self.settings.validated_llama_cpp_host(), 10)
        models = client.list_models()
        size = self.settings.llama_cpp_model_path.stat().st_size if self.settings.llama_cpp_model_path.exists() else 0
        return [{"name": _model_name(self.settings.llama_cpp_model_path),
                 "size_gb": round(size / 1e9, 1), "parameters": None, "quantization": None,
                 "capabilities": ["completion", "tools", "embedding"], "chat": True, "tools": True}
                for item in models]


def _model_name(path: Path) -> str:
    return path.stem or "atalaya"
