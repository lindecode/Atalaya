import json
from types import SimpleNamespace

import pytest

from application.model_advisor import enough_disk, functional_test, model_spec, recommendation
from settings import Settings


@pytest.mark.parametrize(("ram", "expected"), ((6, "qwen3.5:0.8b"), (8, "qwen3.5:2b"),
                                                 (12, "qwen3.5:4b"), (24, "qwen3.5:9b")))
def test_recommendation_scales_main_model_with_ram(ram, expected):
    result = recommendation({"ram_gb": ram, "disk_free_gb": 100, "vram_gb": None, "cpu_threads": 8})

    assert result["analysis"] == expected and result["chat"] == expected
    assert result["embedding"] == "embeddinggemma:latest" and result["fits_disk"]


def test_disk_guard_and_allow_list():
    assert enough_disk("qwen3.5:4b", {"disk_free_gb": 4})[0] is False
    assert enough_disk("qwen3.5:4b", {"disk_free_gb": 10})[0] is True
    with pytest.raises(ValueError, match="catálogo"):
        model_spec("unknown:latest")


def test_recommendation_uses_cpu_and_vram_limits():
    slow = recommendation({"ram_gb": 32, "disk_free_gb": 100, "vram_gb": None, "cpu_threads": 4})
    accelerated = recommendation({"ram_gb": 16, "disk_free_gb": 100, "vram_gb": 8, "cpu_threads": 8})

    assert slow["analysis"] == "qwen3.5:2b"
    assert accelerated["analysis"] == "qwen3.5:9b"


def test_functional_test_checks_chat_json_and_tool_capability():
    class Client:
        calls = 0
        def show(self, _name): return SimpleNamespace(capabilities=["completion", "tools"])
        def chat(self, **kwargs):
            self.calls += 1
            if "tools" in kwargs:
                return SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[SimpleNamespace()]))
            assert kwargs["format"]["additionalProperties"] is False
            return SimpleNamespace(message=SimpleNamespace(content=json.dumps({"ok": True})))

    result = functional_test(Settings(), "qwen3.5:0.8b", Client())

    assert result["ok"] and result["test"] == "chat+json+tools-capability"


def test_functional_test_checks_embedding_vector():
    class Client:
        def show(self, _name): return SimpleNamespace(capabilities=["embedding"])
        def embed(self, **_kwargs): return SimpleNamespace(embeddings=[[0.1, 0.2, 0.3]])

    result = functional_test(Settings(), "embeddinggemma:latest", Client())

    assert result["dimensions"] == 3 and result["test"] == "embedding"
