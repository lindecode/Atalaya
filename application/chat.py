from __future__ import annotations

import json
from typing import Any

from application.harness import SYSTEM_POLICY, SecureChatHarness


TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "additionalProperties": False}}}
    for name, description, properties in (
        ("get_alerts", "Consulta alertas", {"severity": {"type": "string"}, "since": {"type": "string"}}),
        ("get_auth_events", "Consulta accesos y RDP", {"event_id": {"type": "integer"}, "source_ip": {"type": "string"}, "since": {"type": "string"}}),
        ("get_connections", "Consulta conexiones", {"process": {"type": "string"}, "remote_ip": {"type": "string"}, "since": {"type": "string"}}),
        ("get_file_events", "Consulta archivos", {"path_contains": {"type": "string"}, "action": {"type": "string"}, "since": {"type": "string"}}),
        ("get_file_reputation", "Consulta reputación ya almacenada de ejecutables; no envía archivos ni hace llamadas externas",
         {"sha256": {"type": "string"}, "path_contains": {"type": "string"}, "verdict": {"type": "string"}, "since": {"type": "string"}}),
        ("get_persistence_new", "Consulta persistencia nueva", {"since": {"type": "string"}}),
        ("search_knowledge", "Busca procedimientos y explicaciones en documentación local confiable",
         {"query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 10}}),
    )
]


class ChatService:
    def __init__(self, settings, tools, client=None, harness=None):
        self.settings = settings
        self.tools = tools
        self.harness = harness or SecureChatHarness()
        if client is None:
            from ollama import Client
            client = Client(host=settings.validated_ollama_host(), timeout=settings.llm_timeout_seconds)
        self.client = client

    def ask(self, question: str):
        messages = [
            {"role": "system", "content": SYSTEM_POLICY},
            {"role": "user", "content": self.harness.sanitize_question(question)},
        ]
        trace = []
        for _ in range(5):
            response = _chat(self.client, model=self.settings.ollama_model, messages=messages, tools=TOOL_SCHEMAS, think=False)
            message = response.message
            calls = getattr(message, "tool_calls", None) or []
            if not calls:
                return {"answer": self.harness.validate_answer(message.content, trace), "tool_calls": trace}
            messages.append(message)
            for call in calls:
                function = call.function
                # A small model can send bad arguments (e.g. an unparseable `since`): report it back instead of crashing
                try:
                    args = function.arguments if isinstance(function.arguments, dict) else json.loads(function.arguments)
                    rows = self.tools.call(function.name, args)
                    content = json.dumps(self.harness.tool_payload(function.name, rows), ensure_ascii=False, default=str)
                    trace.append({"name": function.name, "arguments": args, "ids": [row.get("id") for row in rows]})
                except (ValueError, TypeError, KeyError) as exc:
                    content = json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
                    trace.append({"name": function.name, "arguments": function.arguments, "ids": [], "error": str(exc)})
                messages.append({"role": "tool", "tool_name": function.name, "content": content})
        raise RuntimeError("Demasiadas rondas de herramientas")


def _chat(client, **kwargs):
    try:
        return client.chat(**kwargs)
    except Exception as exc:
        if "think" in kwargs and "thinking" in str(exc).casefold():
            kwargs.pop("think")
            return client.chat(**kwargs)
        raise
