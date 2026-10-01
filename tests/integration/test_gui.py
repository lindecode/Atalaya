from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from domain.models import AlertCandidate, EvidenceRef
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


PAGES = [
    "interfaces/gui/app.py",
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
]
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("page", PAGES)
def test_page_loads_with_empty_database(page, tmp_path, monkeypatch):
    database = tmp_path / "empty.db"
    reports = tmp_path / "reports"
    monkeypatch.setenv("NETWORK_LLM_DB", str(database))
    monkeypatch.setenv("NETWORK_LLM_REPORTS", str(reports))
    SQLiteRepository(replace(Settings(), database_path=database, reports_dir=reports)).initialize()

    app = AppTest.from_file(ROOT / page, default_timeout=10).run()

    assert not app.exception


def test_alert_workflow_and_xss_literal(tmp_path, monkeypatch):
    database = tmp_path / "fixtures.db"
    reports = tmp_path / "reports"
    monkeypatch.setenv("NETWORK_LLM_DB", str(database))
    monkeypatch.setenv("NETWORK_LLM_REPORTS", str(reports))
    repository = SQLiteRepository(replace(Settings(), database_path=database, reports_dir=reports))
    repository.initialize()
    payload = "<img src=x onerror=alert(1)>.txt"
    alert_id = repository.save_alerts([AlertCandidate(
        "2026-10-01T12:00:00+00:00", "R11", "medium", "Script nuevo", payload,
        {"path": payload}, (EvidenceRef("file_event", 1, {"id": 1, "path": payload}),), "fixture",
    )])[0]

    alert_app = AppTest.from_file(ROOT / "interfaces/gui/pages/2_Alertas.py", default_timeout=10).run()
    assert not alert_app.exception
    assert payload in str(alert_app.dataframe[0].value)
    confirm = next(button for button in alert_app.button if button.label == "Confirmar")
    confirm.click().run()
    with connect(database, readonly=True) as db:
        assert db.execute("SELECT status FROM alerts WHERE id=?", (alert_id,)).fetchone()[0] == "confirmed"
