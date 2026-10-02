from dataclasses import replace
from types import SimpleNamespace

from application.chat import ChatService
from application.tool_router import SecureToolRouter
from settings import Settings


class SQLTools:
    def call(self, name, args): raise AssertionError("No debía consultar SQL")


class Rag:
    def as_tool_rows(self, query, top_k):
        return [{"id": "K:5", "citation": "[K:5]", "source": "README.man.md", "section": "RDP",
                 "trust_level": "trusted", "content": "Revise el evento 1149."}]


class Client:
    def __init__(self, citation="K:5"): self.calls = 0; self.citation = citation
    def chat(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            function = SimpleNamespace(name="search_knowledge", arguments={"query": "investigar RDP", "top_k": 3})
            return SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[SimpleNamespace(function=function)]))
        assert "TRUSTED_KNOWLEDGE" in kwargs["messages"][-1]["content"]
        return SimpleNamespace(message=SimpleNamespace(content=f"Revise 1149 [{self.citation}]", tool_calls=[]))


def test_chat_rag_accepts_only_retrieved_citation():
    settings = replace(Settings(), ollama_model="fake")
    tools = SecureToolRouter(SQLTools(), Rag())
    valid = ChatService(settings, tools, Client()).ask("¿Cómo investigo RDP?")
    invalid = ChatService(settings, tools, Client("K:999")).ask("¿Cómo investigo RDP?")
    assert "[K:5]" in valid["answer"]
    assert invalid["answer"].startswith("Respuesta rechazada")

