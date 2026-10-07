from __future__ import annotations

from dataclasses import replace


def provider_name(settings) -> str:
    configured = settings.llm_provider
    if configured == "auto":
        return "llama_cpp" if settings.llama_cpp_executable.is_file() and settings.llama_cpp_model_path.is_file() else "ollama"
    if configured not in {"ollama", "llama_cpp"}:
        raise ValueError("Proveedor LLM inválido")
    return configured


def build_components(settings):
    name = provider_name(settings)
    if name == "llama_cpp":
        from infrastructure.llama_cpp.runtime import ensure_running
        from infrastructure.llama_cpp.client import LlamaCppClient
        from infrastructure.llama_cpp.provider import LlamaCppAnalyzer, LlamaCppEmbeddingProvider, LlamaCppModelCatalog
        ensure_running(settings)
        model = settings.llama_cpp_model_path.stem
        effective = replace(settings, ollama_model=model, ollama_embedding_model=model)
        return effective, LlamaCppAnalyzer(effective), LlamaCppClient(
            effective.validated_llama_cpp_host(), effective.llm_timeout_seconds), LlamaCppEmbeddingProvider, LlamaCppModelCatalog
    from infrastructure.ollama.analyzer import OllamaAnalyzer
    from infrastructure.ollama.client import build_chat_client
    from infrastructure.ollama.embeddings import OllamaEmbeddingProvider
    from infrastructure.ollama.models import OllamaModelCatalog
    return settings, OllamaAnalyzer(settings), build_chat_client(settings), OllamaEmbeddingProvider, OllamaModelCatalog
