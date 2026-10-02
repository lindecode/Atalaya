from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from domain.models import AlertCandidate, EvidenceRef
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


PAGES = [
    "interfaces/gui/app.py",
    "interfaces/gui/pages/0_Panel.py",
    "interfaces/gui/pages/1_Resumen.py",
    "interfaces/gui/pages/2_Alertas.py",
    "interfaces/gui/pages/3_Conexiones.py",
    "interfaces/gui/pages/4_Accesos.py",
    "interfaces/gui/pages/5_Archivos.py",
    "interfaces/gui/pages/6_Persistencia.py",
    "interfaces/gui/pages/7_Firewall.py",
    "interfaces/gui/pages/8_Informes.py",
    "interfaces/gui/pages/9_Chat.py",
    "interfaces/gui/pages/10_Estado.py",
    "interfaces/gui/pages/11_Primeros_pasos.py",
]
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("page", PAGES)
def test_page_loads_with_empty_database(page, tmp_path, monkeypatch):
    database = tmp_path / "empty.db"
    reports = tmp_path / "reports"
    monkeypatch.setenv("ATALAYA_DB", str(database))
    monkeypatch.setenv("ATALAYA_REPORTS", str(reports))
    SQLiteRepository(replace(Settings(), database_path=database, reports_dir=reports)).initialize()

    app = AppTest.from_file(ROOT / page, default_timeout=30).run()

    assert not app.exception


def test_alert_workflow_and_xss_literal(tmp_path, monkeypatch):
    database = tmp_path / "fixtures.db"
    reports = tmp_path / "reports"
    monkeypatch.setenv("ATALAYA_DB", str(database))
    monkeypatch.setenv("ATALAYA_REPORTS", str(reports))
    repository = SQLiteRepository(replace(Settings(), database_path=database, reports_dir=reports))
    repository.initialize()
    payload = "<img src=x onerror=alert(1)>.txt"
    alert_id = repository.save_alerts([AlertCandidate(
        datetime.now(timezone.utc).isoformat(), "R11", "medium", "Script nuevo", payload,
        {"path": payload}, (EvidenceRef("file_event", 1, {"id": 1, "path": payload}),), "fixture",
    )])[0]

    alert_app = AppTest.from_file(ROOT / "interfaces/gui/pages/2_Alertas.py", default_timeout=30).run()
    assert not alert_app.exception
    assert payload in str(alert_app.dataframe[0].value)
    confirm = next(button for button in alert_app.button if button.label == "Confirmar")
    confirm.click().run()
    with connect(database, readonly=True) as db:
        assert db.execute("SELECT status FROM alerts WHERE id=?", (alert_id,)).fetchone()[0] == "confirmed"


@pytest.mark.parametrize("page", ["interfaces/gui/pages/0_Panel.py", "interfaces/gui/pages/3_Conexiones.py"])
def test_network_pages_draw_the_flow_map(page, tmp_path, monkeypatch):
    from domain.models import CollectionResult, NetworkConnection

    database = tmp_path / "net.db"
    monkeypatch.setenv("ATALAYA_DB", str(database))
    monkeypatch.setenv("ATALAYA_REPORTS", str(tmp_path / "reports"))
    repository = SQLiteRepository(replace(Settings(), database_path=database, reports_dir=tmp_path / "reports"))
    repository.initialize()
    now = datetime.now(timezone.utc).isoformat()
    run_id = repository.start_run("collect", now, False)
    evil_path = "C:/Users/me/Downloads/evil.exe"
    rows = (
        NetworkConnection(now, "psutil", "tcp", "outbound", "192.168.1.5", 50001, "93.184.216.34", 443, "ESTABLISHED", 10, "msedge.exe", None, None),
        NetworkConnection(now, "psutil", "tcp", "outbound", "192.168.1.5", 50002, "198.51.100.9", 4444, "ESTABLISHED", 11,
                          "<b>evil</b>.exe", evil_path, None),
        NetworkConnection(now, "psutil", "tcp", "inbound", "192.168.1.5", 3389, "203.0.113.7", 51515, "ESTABLISHED", 12, "svchost.exe", None, None),
        NetworkConnection(now, "psutil", "tcp", "listen", "0.0.0.0", 445, None, None, "LISTEN", 4, "System", None, None),
    )
    repository.save_collection(run_id, CollectionResult("psutil_connections", "connections", rows, "ok"), now)

    app = AppTest.from_file(ROOT / page, default_timeout=30).run()

    assert not app.exception
    import json
    figures = [json.loads(element.proto.spec) for element in app.get("plotly_chart")]
    sankey = next((trace for figure in figures for trace in figure["data"] if trace["type"] == "sankey"), None)
    assert sankey, "no se dibujó el mapa de flujo"
    labels = sankey["node"]["label"]
    # collected names are escaped before reaching Plotly, which renders a subset of HTML
    assert "&lt;b&gt;evil&lt;/b&gt;.exe" in labels and not any("<b>" in label for label in labels)
    assert any(color.startswith("rgba(239,68,68") for color in sankey["link"]["color"])  # port 4444 from Downloads


def test_chat_page_lists_and_opens_saved_conversations(tmp_path, monkeypatch):
    from infrastructure.sqlite.chat_history import SQLiteChatHistory

    database = tmp_path / "chat.db"
    monkeypatch.setenv("ATALAYA_DB", str(database))
    monkeypatch.setenv("ATALAYA_REPORTS", str(tmp_path / "reports"))
    settings = replace(Settings(), database_path=database, reports_dir=tmp_path / "reports")
    SQLiteRepository(settings).initialize()
    history = SQLiteChatHistory(settings)
    now = datetime.now(timezone.utc).isoformat()
    title = "![x](http://evil.example/beacon.png) conexiones"
    session = history.create_session(title, now)
    history.add_message(session, now, "user", title)
    history.add_message(session, now, "assistant", "Hubo 2 conexiones RDP [K:1]", "qwen3.5:4b", [{"name": "get_auth_events", "ids": [7]}], 1200)

    app = AppTest.from_file(ROOT / "interfaces/gui/pages/9_Chat.py", default_timeout=30).run()
    assert not app.exception
    button = next(b for b in app.button if b.key == f"chat-session-{session}")
    assert button.label.startswith(r"\!\[x\]\(http://evil\.example") and "](http" not in button.label  # image escaped

    app = button.click().run()
    assert not app.exception
    assert any("Hubo 2 conexiones RDP" in text.value for text in app.text)


def test_about_dialog_shows_author(tmp_path, monkeypatch):
    database = tmp_path / "about.db"
    monkeypatch.setenv("ATALAYA_DB", str(database))
    monkeypatch.setenv("ATALAYA_REPORTS", str(tmp_path / "reports"))
    SQLiteRepository(replace(Settings(), database_path=database)).initialize()

    app = AppTest.from_file(ROOT / "interfaces/gui/pages/0_Panel.py", default_timeout=30).run()
    app.sidebar.button(key="action-about").click().run()

    assert not app.exception
    assert any("LindeCode" in element.value for element in app.markdown)
