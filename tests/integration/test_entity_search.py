from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from domain.models import AlertCandidate, CollectionResult, EvidenceRef, NetworkConnection
from infrastructure.sqlite.queries import SQLiteQueryRepository
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(timezone.utc)


def _seed(tmp_path, monkeypatch=None):
    database, reports = tmp_path / "search.db", tmp_path / "reports"
    if monkeypatch:
        monkeypatch.setenv("ATALAYA_DB", str(database))
        monkeypatch.setenv("ATALAYA_REPORTS", str(reports))
    settings = replace(Settings(), database_path=database, reports_dir=reports)
    repository = SQLiteRepository(settings)
    repository.initialize()
    run_id = repository.start_run("collect", NOW.isoformat(), False)
    rows = (
        NetworkConnection(NOW.isoformat(), "psutil", "tcp", "outbound", "192.168.1.5", 50001, "203.0.113.7", 4444,
                          "ESTABLISHED", 10, "tool_x.exe", r"C:\Tools\tool_x.exe", None),
        NetworkConnection((NOW - timedelta(days=3)).isoformat(), "psutil", "tcp", "outbound", "192.168.1.5", 50002,
                          "203.0.113.7", 443, "ESTABLISHED", 11, "old.exe", None, None),
        NetworkConnection(NOW.isoformat(), "psutil", "tcp", "outbound", "192.168.1.5", 50003, "198.51.100.1", 443,
                          "ESTABLISHED", 12, "toolAx.exe", None, None),
    )
    repository.save_collection(run_id, CollectionResult("psutil_connections", "connections", rows, "ok"), NOW.isoformat())
    alert_id = repository.save_alerts([AlertCandidate(
        NOW.isoformat(), "R07", "medium", "Puerto remoto sospechoso", "203.0.113.7", {"port": 4444, "remote": "203.0.113.7"},
        (EvidenceRef("connection", 1, {"id": 1, "raddr": "203.0.113.7"}),), "fixture")])[0]
    return settings, alert_id


def test_entity_search_spans_tables_respects_the_window_and_escapes_wildcards(tmp_path):
    settings, alert_id = _seed(tmp_path)
    query = SQLiteQueryRepository(settings)
    since = (NOW - timedelta(hours=24)).isoformat()

    results = query.entity_search("203.0.113.7", since)
    assert [row["process_name"] for row in results["connections"]] == ["tool_x.exe"]  # the 3-day-old one is outside
    assert [row["id"] for row in results["alerts"]] == [alert_id]
    # '_' is literal, not a one-character wildcard that would also match toolAx.exe
    assert [row["process_name"] for row in query.entity_search("tool_x", since)["connections"]] == ["tool_x.exe"]
    assert query.entity_search("%%", since)["connections"] == []
    with pytest.raises(ValueError):
        query.entity_search(" a ", since)


def test_search_page_reads_the_query_from_the_url(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    app = AppTest.from_file(ROOT / "interfaces/gui/pages/13_Buscar.py", default_timeout=30)
    app.query_params["q"] = "203.0.113.7"
    app.run()
    assert not app.exception
    assert any("Conexiones (1)" in tab.label for tab in app.tabs)


def test_alert_link_opens_its_detail_even_outside_the_filters(tmp_path, monkeypatch):
    settings, alert_id = _seed(tmp_path, monkeypatch)
    SQLiteRepository(settings).update_alert_status(alert_id, "dismissed", None, NOW.isoformat())
    app = AppTest.from_file(ROOT / "interfaces/gui/pages/2_Alertas.py", default_timeout=30)
    app.query_params["id"] = str(alert_id)
    app.run()
    assert not app.exception
    assert any(f"alerta #{alert_id}" in element.value for element in app.markdown)
    assert any("Qué revisar" in element.value for element in app.markdown)


def test_connections_filter_by_ip_shows_its_profile(tmp_path, monkeypatch):
    import infrastructure.windows.dns_cache as dns_cache

    _seed(tmp_path, monkeypatch)
    monkeypatch.setattr(dns_cache, "dns_cache_records",
                        lambda timeout=15: [{"Entry": "c2.example.test", "Data": "203.0.113.7", "Type": 1}])
    app = AppTest.from_file(ROOT / "interfaces/gui/pages/3_Conexiones.py", default_timeout=30)
    app.query_params["ip"] = "203.0.113.7"
    app.run()
    assert not app.exception
    assert any("203.0.113.7" in element.value and "####" in element.value for element in app.markdown)
    assert any("c2.example.test" in element.value for element in app.text)
    assert {metric.label: metric.value for metric in app.metric}["Alertas"] == "1"
    assert any("2 de 3 conexiones" in element.value for element in app.caption)  # same run, any age
