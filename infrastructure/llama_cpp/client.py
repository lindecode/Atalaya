from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


class LlamaCppClient:
    """Small OpenAI-compatible client for a loopback-only llama-server."""

    def __init__(self, host: str, timeout: float = 60.0):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}))

    def _request(self, path: str, payload: dict | None = None) -> dict:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(self.host + path, data=body,
                          headers={"Accept": "application/json", "Content-Type": "application/json"},
                          method="GET" if payload is None else "POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"llama-server respondió HTTP {response.status}")
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise RuntimeError(f"llama-server respondió HTTP {exc.code}: {detail}") from exc
        except (URLError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"llama-server no está disponible: {exc}") from exc

    def health(self) -> bool:
        try:
            return self._request("/health").get("status") == "ok"
        except RuntimeError:
            return False

    def list_models(self) -> list[dict]:
        return list(self._request("/v1/models").get("data") or [])

    def chat(self, *, model: str, messages, tools=None, format=None, options=None, **_ignored):
        normalized = [_message_dict(message) for message in messages]
        payload = {"model": model, "messages": normalized, "stream": False}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if format:
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "atalaya_analysis", "strict": True, "schema": format}}
        for source, target in (("temperature", "temperature"), ("top_p", "top_p"),
                               ("top_k", "top_k"), ("seed", "seed")):
            if options and source in options:
                payload[target] = options[source]
        raw = self._request("/v1/chat/completions", payload)
        try:
            message = raw["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("llama-server devolvió una respuesta de chat incompleta") from exc
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            calls.append(SimpleNamespace(id=call.get("id"), function=SimpleNamespace(
                name=function.get("name"), arguments=function.get("arguments", "{}"))))
        return SimpleNamespace(message=SimpleNamespace(content=message.get("content") or "", tool_calls=calls))

    def embed(self, *, model: str, input, **_ignored):
        raw = self._request("/v1/embeddings", {"model": model, "input": list(input)})
        ordered = sorted(raw.get("data") or [], key=lambda item: item.get("index", 0))
        return SimpleNamespace(embeddings=[item["embedding"] for item in ordered])


def _message_dict(message) -> dict:
    if isinstance(message, dict):
        result = dict(message)
        if result.get("role") == "tool":
            tool_name = result.pop("tool_name", "atalaya-tool")
            result.setdefault("tool_call_id", tool_name)
        return result
    result = {"role": "assistant", "content": getattr(message, "content", "") or ""}
    calls = []
    for index, call in enumerate(getattr(message, "tool_calls", None) or []):
        function = call.function
        arguments = function.arguments if isinstance(function.arguments, str) else json.dumps(function.arguments)
        calls.append({"id": getattr(call, "id", None) or f"call-{index}", "type": "function",
                      "function": {"name": function.name, "arguments": arguments}})
    if calls:
        result["tool_calls"] = calls
    return result
