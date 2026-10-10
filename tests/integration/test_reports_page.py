from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

from settings import Settings


def test_reports_page_generates_report_without_external_launcher(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / "atalaya.db", reports_dir=tmp_path / "reports")
    monkeypatch.setattr("interfaces.gui.common.Settings", lambda: settings)
    monkeypatch.setattr("infrastructure.clock.SystemClock.now_iso",
                        lambda self: datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc).isoformat())

    page = Path(__file__).resolve().parents[2] / "interfaces" / "gui" / "views" / "22_Informes.py"
    app = AppTest.from_file(page).run(timeout=20)
    button = next(item for item in app.button if item.label == "Generar informe")
    button.click().run(timeout=20)

    assert list(settings.reports_dir.glob("*.md"))
    assert any("Informe creado:" in item.value for item in app.success)
    assert not any(".bat" in item.value for item in app.markdown)
