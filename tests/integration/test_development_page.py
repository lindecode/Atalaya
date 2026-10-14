from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from streamlit.testing.v1 import AppTest

from application.network_watch import Notice
from infrastructure.sqlite.network_notices import SQLiteNetworkNotices
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings
from tests.unit.test_dev_view import SNAPSHOT

ROOT = Path(__file__).resolve().parents[2]


def test_development_page_shows_servers_debug_warning_and_notices(tmp_path, monkeypatch):
    database = tmp_path / "dev.db"
    monkeypatch.setenv("ATALAYA_DB", str(database))
    monkeypatch.setenv("ATALAYA_REPORTS", str(tmp_path / "reports"))
    settings = replace(Settings(), database_path=database)
    SQLiteRepository(settings).initialize()
    from datetime import datetime, timezone
    SQLiteNetworkNotices(settings).add([Notice(datetime.now(timezone.utc).isoformat(), "client", "internet",
                                               "45.1.2.3", 8080, "java.exe", "")])
    import infrastructure.windows.dev_inventory as inventory
    monkeypatch.setattr(inventory, "snapshot", lambda now_iso=None: SNAPSHOT)

    app = AppTest.from_file(ROOT / "interfaces/gui/views/04_Desarrollo.py", default_timeout=30).run()
    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Servidores"] == "3" and metrics["Expuestos a la red"] == "2"
    assert metrics["Depuración expuesta"] == "1" and metrics["Clientes externos ahora"] == "2"
    assert metrics["Avisos de red"] == "1"
    assert any("Inspector de Node.js" in error.value for error in app.error)
    assert any("app.jar" in text.value for text in app.text)  # the Java card names the jar, not just java.exe
    assert any("Aún no hay recolecciones" in info.value for info in app.info)  # empty timeline, no crash

    app.number_input(key="dev-port").set_value(8080).run()
    assert not app.exception
    assert any(code.value == "Stop-Process -Id 10" for code in app.code)
    app.number_input(key="dev-port").set_value(4444).run()
    assert any("está libre" in success.value for success in app.success)
