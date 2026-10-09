from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.queries import SQLiteQueryRepository
from infrastructure.sqlite.repositories import SQLiteRepository
from infrastructure.sqlite.section_summaries import SQLiteSectionSummaryStore
from settings import Settings

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(timezone.utc)
INCIDENT = {"title": "Puerto sospechoso", "alert_ids": [7], "severity": "high", "narrative": "<b>texto</b> del LLM",
            "benign_explanations": [], "false_positive_likelihood": "low", "recommended_actions": ["Revisar"]}


def _seed(tmp_path, monkeypatch=None):
    database = tmp_path / "history.db"
    if monkeypatch:
        monkeypatch.setenv("ATALAYA_DB", str(database))
        monkeypatch.setenv("ATALAYA_REPORTS", str(tmp_path / "reports"))
    settings = replace(Settings(), database_path=database, reports_dir=tmp_path / "reports")
    repository = SQLiteRepository(settings)
    repository.initialize()
    run_id = repository.start_run("analyze", NOW.isoformat(), False)
    repository.save_llm_analysis(run_id, (NOW - timedelta(hours=2)).isoformat(), "qwen", [7], 100,
                                 {"summary": "Riesgo alto por un puerto.", "overall_risk": "high",
                                  "incidents": [INCIDENT]}, None, 41_000)
    repository.save_llm_analysis(run_id, (NOW - timedelta(days=3)).isoformat(), "qwen", [], 0, None, "TimeoutError", 60_000)
    store = SQLiteSectionSummaryStore(settings)
    store.save("firewall", (NOW - timedelta(hours=1)).isoformat(), "manual", 24, "gemma", "h", {"datos": {"bloqueos": 3}},
               {"summary": "Pocos bloqueos.", "highlights": ["IP insistente"], "risk": "low"}, None)
    with connect(database) as db:  # a corrupt row must not break the page
        db.execute("""INSERT INTO section_summaries(section, created_at, trigger, window_hours, model, digest_hash,
                      digest_json, result_json) VALUES ('panel', ?, 'auto', 24, 'm', 'h', '{', '{')""", (NOW.isoformat(),))
    return settings


def test_history_merges_both_sources_newest_first_and_respects_the_period(tmp_path):
    settings = _seed(tmp_path)
    query = SQLiteQueryRepository(settings)
    everything = query.analysis_history(None)
    assert [item["kind"] for item in everything] == ["seccion", "seccion", "alertas", "alertas"]
    corrupt, firewall, alert, failed = everything
    assert corrupt["result"] is None and corrupt["data"] is None
    assert firewall["risk"] == "low" and firewall["points"] == ["IP insistente"] and firewall["data"]["datos"]["bloqueos"] == 3
    assert alert["risk"] == "high" and alert["points"] == ["Puerto sospechoso"] and alert["alerts"] == 1
    assert failed["error"] == "TimeoutError" and failed["risk"] is None
    last_day = query.analysis_history((NOW - timedelta(hours=24)).isoformat())
    assert "alertas-2" not in {item["key"] for item in last_day} and len(last_day) == 3


def test_history_page_draws_charts_and_cards_with_llm_text_as_plain_text(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    app = AppTest.from_file(ROOT / "interfaces/gui/views/20_Historial.py", default_timeout=30).run()
    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Análisis"] == "4" and metrics["Fallidos"] == "2" and metrics["Altos o críticos"] == "1"
    figures = [json.loads(element.proto.spec) for element in app.get("plotly_chart")]
    assert {trace["type"] for figure in figures for trace in figure["data"]} >= {"scatter", "heatmap", "bar"}
    assert any(element.value == "<b>texto</b> del LLM" for element in app.text)  # never rendered as HTML

    app.multiselect(key="history-risk").select("low").run()
    assert {metric.label: metric.value for metric in app.metric}["Análisis"] == "1"
