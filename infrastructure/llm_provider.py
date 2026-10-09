from __future__ import annotations

from dataclasses import replace
from pathlib import Path


def effective_settings(settings, role: str | None = None):
    """Apply only GGUF files explicitly assigned in Atalaya's local registry."""
    from infrastructure.ai_registry import ModelRegistry
    registry = ModelRegistry()
    selected_role = role or getattr(settings, "llm_role", "chat")
    chat = registry.assigned(selected_role) if selected_role != "embedding" else None
    chat = chat or registry.assigned("chat") or registry.assigned("analysis")
    embedding = registry.assigned("embedding")
    changes = {}
    runtime = registry.runtime()
    if runtime:
        changes["llama_cpp_executable"] = Path(runtime["path"])
    if chat:
        changes["llama_cpp_model_path"] = Path(chat.path)
    if embedding:
        changes["llama_cpp_embedding_model_path"] = Path(embedding.path)
    return replace(settings, **changes) if changes else settings


def ollama_installed() -> bool:
    import os
    import shutil
    if shutil.which("ollama"):
        return True
    return (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe").is_file()


def provider_name(settings) -> str:
    settings = effective_settings(settings)
    from infrastructure.ai_registry import ModelRegistry
    configured = settings.llm_provider
    if configured == "auto":
        configured = ModelRegistry().provider()
    if configured == "auto":
        if settings.llama_cpp_executable.is_file() and settings.llama_cpp_model_path.is_file():
            return "llama_cpp"
        return "ollama" if ollama_installed() else "none"
    if configured not in {"ollama", "llama_cpp", "none"}:
        raise ValueError("Proveedor LLM inválido")
    return configured


def build_components(settings):
    settings = effective_settings(settings)
    name = provider_name(settings)
    if name == "llama_cpp":
        from infrastructure.llama_cpp.runtime import ensure_running
        from infrastructure.llama_cpp.client import LlamaCppClient
        from infrastructure.llama_cpp.credentials import load_or_create_key
        from infrastructure.llama_cpp.endpoints import runtime_host
        from infrastructure.llama_cpp.provider import LlamaCppAnalyzer, LlamaCppEmbeddingProvider, LlamaCppModelCatalog
        ensure_running(settings)
        model = settings.llama_cpp_model_path.stem
        effective = replace(settings, ollama_model=model,
                            ollama_embedding_model=settings.llama_cpp_embedding_model_path.stem)
        return effective, LlamaCppAnalyzer(effective), LlamaCppClient(
            runtime_host(effective, "chat"), effective.llm_timeout_seconds,
            load_or_create_key(effective, "chat")), LlamaCppEmbeddingProvider, LlamaCppModelCatalog
    if name == "none":
        from infrastructure.disabled_llm import (DisabledAnalyzer, DisabledClient, DisabledEmbeddingProvider,
                                                 DisabledModelCatalog)
        return settings, DisabledAnalyzer(), DisabledClient(), DisabledEmbeddingProvider, DisabledModelCatalog
    from infrastructure.ollama.analyzer import OllamaAnalyzer
    from infrastructure.ollama.client import build_chat_client
    from infrastructure.ollama.embeddings import OllamaEmbeddingProvider
    from infrastructure.ollama.models import OllamaModelCatalog
    return settings, OllamaAnalyzer(settings), build_chat_client(settings), OllamaEmbeddingProvider, OllamaModelCatalog
