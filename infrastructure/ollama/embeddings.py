from __future__ import annotations


class OllamaEmbeddingProvider:
    def __init__(self, settings, model: str | None = None, client=None):
        self.model = model or settings.ollama_embedding_model
        if client is None:
            from ollama import Client
            client = Client(host=settings.validated_ollama_host(), timeout=settings.llm_timeout_seconds)
        self.client = client

    def embed(self, texts):
        if not texts: return []
        response = self.client.embed(model=self.model, input=list(texts), truncate=True)
        vectors = getattr(response, "embeddings", None)
        if vectors is None and isinstance(response, dict): vectors = response.get("embeddings")
        if not vectors or len(vectors) != len(texts):
            raise ValueError("Ollama devolvió embeddings incompletos")
        return [list(map(float, vector)) for vector in vectors]

