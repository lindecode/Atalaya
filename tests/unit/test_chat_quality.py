from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from application import chat_intents
from application.chat import ChatService
from application.chat_evals import CASES, run
from infrastructure.sqlite.chat_tools import ROW_LIMIT, SQLiteQueryTools
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


def _settings(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "q.db", language="es")
    SQLiteRepository(settings).initialize()
    return settings


def _alerts(settings, rows):
    with connect(settings.database_path) as db:
        for index, (severity, status) in enumerate(rows):
            db.execute("""INSERT INTO alerts(ts, rule_id, severity, title, evidence, dedup_key, status)
                          VALUES (datetime('now'), ?, ?, ?, '{}', ?, ?)""",
                       (f"R0{index % 3}", severity, f"alerta {index}", f"k{index}", status))


def _reply(content="", calls=()):
    return SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=list(calls)))


def test_alerts_accept_several_severities_in_any_case_and_language(tmp_path):
    settings = _settings(tmp_path)
    _alerts(settings, [("critical", "new"), ("high", "analyzed"), ("medium", "new"), ("high", "dismissed")])
    tools = SQLiteQueryTools(settings)
    for value in ("CRITICAL,HIGH", ["crítica", "Alta"], "critical y high"):
        result = tools.call("get_alerts", {"severity": value})
        assert [row["severity"] for row in result["rows"]] == ["critical", "high"]  # most severe first, open only
        assert result["summary"]["by_severity"] == {"critical": 1, "high": 1}
    assert tools.call("get_alerts", {"status": "all"})["summary"]["total"] == 4
    with pytest.raises(ValueError, match="Valores admitidos"):
        tools.call("get_alerts", {"severity": "urgente"})


def test_results_are_capped_and_summarized(tmp_path):
    settings = _settings(tmp_path)
    _alerts(settings, [("high", "new")] * (ROW_LIMIT + 10))
    result = SQLiteQueryTools(settings).call("get_alerts", {})
    assert len(result["rows"]) == ROW_LIMIT
    assert result["summary"]["total"] == ROW_LIMIT + 10 and "note" in result["summary"]
    assert set(result["summary"]["by_rule"]) == {"R00", "R01", "R02"}
    overview = SQLiteQueryTools(settings).call("get_overview", {})["summary"]
    assert overview["open_alerts_by_severity"] == {"high": ROW_LIMIT + 10}


def test_intent_router_picks_the_obvious_tools():
    assert chat_intents.plan("¿Qué alertas críticas hay?")[0][0] == "get_alerts"
    assert chat_intents.plan("¿Quién entró por RDP esta semana?") == [("get_auth_events", {"since": "7d"})]
    assert chat_intents.plan("¿Qué puertos tengo abiertos?") == [("get_connections", {"direction": "listen"})]
    assert [name for name, _ in chat_intents.plan("¿Cómo investigo alertas de RDP?")] == ["search_knowledge"]
    assert chat_intents.plan("hola") == []


def test_preloaded_evidence_reaches_the_model_and_options_set_the_context(tmp_path):
    settings = _settings(tmp_path)
    _alerts(settings, [("critical", "new")])
    seen = {}

    class Client:
        def chat(self, **kwargs):
            seen.update(kwargs)
            return _reply("La alerta 1 es crítica.")

    result = ChatService(settings, SQLiteQueryTools(settings), Client()).ask("¿Qué alertas críticas hay?")
    system = [message["content"] for message in seen["messages"] if message["role"] == "system"]
    assert any(text.startswith("<preloaded_evidence>") and '"id": 1' in text for text in system)
    assert "Fecha y hora actual" in system[0] and "el usuario no puede" in system[0]
    assert seen["options"]["num_ctx"] == settings.chat_context_tokens
    assert result["tool_calls"][0] == {"name": "get_alerts", "arguments": {}, "ids": [1], "prefetch": True}
    assert result["answer"] == "La alerta 1 es crítica."


def test_evasive_answer_is_retried_once_then_replaced_by_the_evidence(tmp_path):
    settings = _settings(tmp_path)
    _alerts(settings, [("high", "new")])

    class Client:
        def __init__(self, answers): self.answers, self.messages = list(answers), []
        def chat(self, **kwargs):
            self.messages = kwargs["messages"]
            return _reply(self.answers.pop(0))

    fixed = Client(["Puedes usar la herramienta get_alerts.", "Hay 1 alerta alta abierta: la 1."])
    result = ChatService(settings, SQLiteQueryTools(settings), fixed).ask("alertas")
    assert result["answer"] == "Hay 1 alerta alta abierta: la 1."
    assert "el usuario no puede" in fixed.messages[-1]["content"]

    stuck = Client(["Use get_alerts para verlas.", ""])
    result = ChatService(settings, SQLiteQueryTools(settings), stuck).ask("alertas")
    assert result["fallback"] and "ID 1" in result["answer"] and "get_alerts" in result["answer"]


def test_evals_score_a_model_and_survive_errors():
    class Chat:
        def ask(self, question, lang="es"):
            if "RDP" in question:
                raise RuntimeError("boom")
            tool = next(case.tools[0] for case in CASES if case.question == question)
            text = "The alert 3 is open." if lang == "en" else "La alerta 3 es la más grave de las abiertas."
            return {"answer": text, "tool_calls": [{"name": tool, "ids": [3]}]}

    report = run(Chat())
    failed = [case for case in report["cases"] if case.get("error")]
    assert len(report["cases"]) == len(CASES) and len(failed) == 2
    assert all(case["passed"] == case["total"] for case in report["cases"] if not case.get("error"))
    assert 0 < report["score"] < 100


def test_small_chat_models_are_detected_by_effective_size():
    from interfaces.gui.local_ai import effective_billions
    assert effective_billions("gemma4:e2b", "4.6B") == 2
    assert effective_billions("qwen3.5:0.8b", "873.44M") == pytest.approx(0.873, abs=1e-3)
    assert effective_billions("qwen3.5:4b", "4.7B") == 4.7
    assert effective_billions("x", None) is None
