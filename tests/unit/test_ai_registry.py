import json
import struct
from dataclasses import replace

import pytest

from infrastructure.ai_registry import ModelRegistry, hardware_recommendations, inspect_gguf
from infrastructure.llm_provider import effective_settings, provider_name
from settings import Settings


def _gguf(path, size=64):
    path.write_bytes(b"GGUF" + struct.pack("<I", 3) + b"\0" * (size - 8))
    return path


def test_registry_only_accepts_explicit_valid_gguf_and_assigns_roles(tmp_path, monkeypatch):
    registry = ModelRegistry(tmp_path / "registry.json")
    model = registry.register(_gguf(tmp_path / "chat.gguf"), ("chat", "analysis"))
    registry.assign("chat", model.id)

    assert registry.assigned("chat").sha256 == model.sha256
    assert registry.assigned("embedding") is None
    with pytest.raises(ValueError, match="autorizado"):
        registry.assign("embedding", model.id)
    invalid = tmp_path / "bad.gguf"; invalid.write_bytes(b"bad" * 20)
    with pytest.raises(ValueError, match="firma GGUF"):
        inspect_gguf(invalid)


def test_registered_runtime_and_model_feed_effective_settings(tmp_path, monkeypatch):
    registry_file = tmp_path / "models" / "registry.json"
    registry = ModelRegistry(registry_file)
    model = registry.register(_gguf(tmp_path / "chat.gguf"), ("chat",))
    registry.assign("chat", model.id)
    runtime = tmp_path / "llama-server.exe"; runtime.write_bytes(b"MZ" + b"\0" * 30)
    registry.register_runtime(runtime)
    monkeypatch.setattr("infrastructure.ai_registry.registry_path", lambda: registry_file)

    effective = effective_settings(replace(Settings(), llama_cpp_executable=tmp_path / "missing.exe",
                                            llama_cpp_model_path=tmp_path / "missing.gguf"))

    assert effective.llama_cpp_executable == runtime.resolve()
    assert effective.llama_cpp_model_path == (tmp_path / "chat.gguf").resolve()
    assert provider_name(effective) == "llama_cpp"
    registry.verify_execution("chat")
    runtime.write_bytes(b"MZ" + b"changed")
    with pytest.raises(RuntimeError, match="cambió"):
        registry.verify_execution("chat")


def test_hardware_recommendation_uses_small_summary_and_respects_ram(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    small = registry.register(_gguf(tmp_path / "small.gguf", 64), ("summary", "chat"))
    large = registry.register(_gguf(tmp_path / "large.gguf", 128), ("summary", "chat", "analysis"))

    result = hardware_recommendations([small, large], 1024)

    assert result["summary"] == small.id and result["chat"] == large.id and result["analysis"] == large.id
