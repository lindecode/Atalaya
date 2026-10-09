from __future__ import annotations


MESSAGE = "No hay un proveedor de IA local configurado; la recolección y las reglas siguen disponibles"


class DisabledAnalyzer:
    model = "sin-ia"

    def analyze(self, _alerts):
        raise RuntimeError(MESSAGE)


class DisabledClient:
    def chat(self, **_kwargs):
        raise RuntimeError(MESSAGE)


class DisabledEmbeddingProvider:
    def __init__(self, _settings, _model=None): pass
    model = "sin-ia"
    def embed(self, _texts): raise RuntimeError(MESSAGE)


class DisabledModelCatalog:
    def __init__(self, _settings): pass
    def list_models(self): return []
