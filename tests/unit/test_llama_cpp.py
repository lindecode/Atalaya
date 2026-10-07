from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from infrastructure.llama_cpp.client import LlamaCppClient, _message_dict
from infrastructure.llama_cpp.provider import LlamaCppAnalyzer, LlamaCppEmbeddingProvider
from infrastructure.llama_cpp.runtime import server_command
from infrastructure.llm_provider import provider_name
from settings import Settings


class Response:
    status = 200
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, *_): return json.dumps(self.payload).encode()


class Opener:
    def __init__(self, payload): self.payload, self.request = payload, None
    def open(self, request, timeout): self.request = request; return Response(self.payload)


def test_chat_translates_openai_tool_calls_and_structured_output():
    opener = Opener({"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "function": {
        "name": "get_alerts", "arguments": "{\"severity\":\"high\"}"}}]}}]})
    client = LlamaCppClient("http://127.0.0.1:11435")
    client.opener = opener

    response = client.chat(model="local", messages=[{"role": "user", "content": "alertas"}],
                           tools=[{"type": "function"}], format={"type": "object"},
                           options={"temperature": 0.1})

    assert response.message.tool_calls[0].id == "c1"
    assert response.message.tool_calls[0].function.name == "get_alerts"
    sent = json.loads(opener.request.data)
    assert sent["response_format"] == {"type": "json_schema", "schema": {"type": "object"}}
    assert sent["temperature"] == 0.1 and sent["stream"] is False


def test_client_sends_bearer_key_only_when_configured():
    opener = Opener({"status": "ok"})
    client = LlamaCppClient("http://127.0.0.1:11435", api_key="secret-local-key")
    client.opener = opener

    assert client.health()
    assert opener.request.headers["Authorization"] == "Bearer secret-local-key"


def test_assistant_and_tool_messages_are_openai_compatible():
    function = SimpleNamespace(name="get_alerts", arguments={"severity": "high"})
    assistant = SimpleNamespace(content="", tool_calls=[SimpleNamespace(id="call-7", function=function)])

    assert _message_dict(assistant)["tool_calls"][0]["id"] == "call-7"
    tool = _message_dict({"role": "tool", "tool_name": "get_alerts", "tool_call_id": "call-7", "content": "[]"})
    assert tool["tool_call_id"] == "call-7" and "tool_name" not in tool


def test_auto_provider_uses_llama_cpp_only_when_runtime_and_model_exist(tmp_path):
    executable, model = tmp_path / "llama-server.exe", tmp_path / "model.gguf"
    settings = replace(Settings(), llama_cpp_executable=executable, llama_cpp_model_path=model, llm_provider="auto")
    assert provider_name(settings) == "ollama"
    executable.write_bytes(b"exe"); model.write_bytes(b"gguf")
    assert provider_name(settings) == "llama_cpp"
    assert provider_name(replace(settings, llm_provider="ollama")) == "ollama"


def test_llama_cpp_analyzer_keeps_the_same_validated_security_schema(tmp_path):
    payload = {"summary": "Revisar", "overall_risk": "high", "incidents": [{
        "title": "Incidente", "alert_ids": [7, 999], "severity": "low", "narrative": "Sospechoso",
        "benign_explanations": [], "false_positive_likelihood": "low", "recommended_actions": ["Revisar"]}]}

    class Client:
        def chat(self, **kwargs):
            assert kwargs["format"]["additionalProperties"] is False
            return SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))

    settings = replace(Settings(), llama_cpp_model_path=tmp_path / "secure.gguf")
    analyzer = LlamaCppAnalyzer(settings)
    analyzer._client = lambda: Client()
    result, _, ids = analyzer.analyze([{"id": 7, "rule_id": "R08", "severity": "critical",
                                        "title": "Masivo", "evidence": {}, "examples": []}])

    assert ids == [7] and result["incidents"][0]["alert_ids"] == [7]
    assert result["incidents"][0]["severity"] == "high"


def test_llama_cpp_embeddings_are_normalized_to_floats(tmp_path):
    client = SimpleNamespace(embed=lambda **_: SimpleNamespace(embeddings=[[1, 2], [3, 4]]))
    provider = LlamaCppEmbeddingProvider(replace(Settings(), llama_cpp_model_path=tmp_path / "e.gguf"), client=client)

    assert provider.embed(["a", "b"]) == [[1.0, 2.0], [3.0, 4.0]]


def test_chat_and_embedding_servers_have_separate_hardened_commands(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "data" / "atalaya.db",
                       llama_cpp_executable=tmp_path / "llama-server.exe",
                       llama_cpp_model_path=tmp_path / "chat.gguf",
                       llama_cpp_embedding_model_path=tmp_path / "embed.gguf")
    chat = server_command(settings, "chat")
    embedding = server_command(settings, "embedding")

    assert "--embedding" not in chat and "--jinja" in chat
    assert "--embedding" in embedding and "--jinja" not in embedding
    assert "11435" in chat and "11436" in embedding
    assert "--api-key-file" in chat and "--no-webui" in chat
    assert str(settings.llama_cpp_model_path) in chat
    assert str(settings.llama_cpp_embedding_model_path) in embedding
