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
    assert chat_intents.plan("What are the most important open alerts?")[0][0] == "get_alerts"
    assert chat_intents.plan("¿Qué es un 4625?")[0][0] == "search_knowledge"


def test_concrete_entities_pin_the_tool_and_filter():
    assert chat_intents.plan("¿Quién es 79.133.168.76?")[0] == ("get_connections", {"remote_ip": "79.133.168.76", "since": "7d"})
    assert chat_intents.plan("¿Por qué R11 tiene tantas alertas?") == [("get_alerts", {"rule": "R11"})]  # not a how-to
    assert [name for name, _ in chat_intents.plan("¿Qué hizo pythonw.exe ayer?")] == ["get_processes", "get_connections"]
    assert chat_intents.plan("¿Cambió algo desde ayer?") == [("get_overview", {"since": "48h"})]
    assert chat_intents.plan("reunión a las 10:30:00") == []


def test_an_answer_without_any_evidence_is_retried(tmp_path):
    settings = _settings(tmp_path)
    answers = ["Todo parece normal.", "Según el panorama no hay alertas abiertas."]

    class Client:
        def chat(self, **kwargs):
            if len(answers) == 1 and not any(m.get("role") == "tool" for m in kwargs["messages"] if isinstance(m, dict)):
                assert "No consultaste ninguna evidencia" in kwargs["messages"][-1]["content"]
            return _reply(answers.pop(0))

    result = ChatService(settings, SQLiteQueryTools(settings), Client()).ask("¿Está bien mi equipo hoy, sí o no?")
    assert result["answer"] == "Según el panorama no hay alertas abiertas." and not answers


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
    assert result["fallback"] and "ID 1" in result["answer"] and "**Alertas**" in result["answer"]

    second_try = Client(["Ejecute get_alerts.", "Según get_alerts hay 1 alerta alta (ID 1)."])
    result = ChatService(settings, SQLiteQueryTools(settings), second_try).ask("alertas")
    assert result["answer"] == "Según alertas hay 1 alerta alta (ID 1)."  # kept after the retry, tool name rewritten


def test_naming_a_tool_is_not_deferring_to_the_user():
    from application.chat import DEFERS_TO_USER, humanize
    assert not DEFERS_TO_USER.search("Se encontraron 37 eventos en `get_auth_events` (4625).")
    assert DEFERS_TO_USER.search("Utilice `get_auth_events` con failed_only=true para ver el detalle.")
    assert DEFERS_TO_USER.search("Puedes usar la herramienta de alertas.")
    assert humanize("ver `get_connections`", "en") == "ver connections"


def test_evals_score_a_model_and_survive_errors():
    class Chat:
        def ask(self, question, lang="es"):
            if "RDP" in question:
                raise RuntimeError("boom")
            tool = next(case.tools[0] for case in CASES if case.question == question)
            text = "The alert 3 is open." if lang == "en" else "La alerta 3 del puerto 8080 es la más grave de las abiertas."
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


def test_ports_and_my_servers_go_to_the_live_server_list():
    assert chat_intents.plan("¿Quién se conectó a mi servidor del 8080?") == [("get_dev_servers", {"port": 8080})]
    assert chat_intents.plan("¿Qué hay en localhost:5173?") == [("get_dev_servers", {"port": 5173})]
    assert chat_intents.plan("¿Tengo puertos de depuración abiertos hoy?") == [("get_dev_servers", {})]
    assert chat_intents.plan("¿Qué puertos tengo abiertos?") == [("get_connections", {"direction": "listen"})]
