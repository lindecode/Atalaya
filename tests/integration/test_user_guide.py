from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from settings import Settings


def test_user_guide_describes_sections_and_all_rules(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / "atalaya.db", reports_dir=tmp_path / "reports")
    monkeypatch.setattr("interfaces.gui.common.Settings", lambda: settings)
    page = Path(__file__).resolve().parents[2] / "interfaces" / "gui" / "views" / "00_Guia.py"

    app = AppTest.from_file(page).run(timeout=20)

    assert not app.exception
    assert len(app.tabs) == 5
    rules = next(frame.value for frame in app.dataframe if "Regla" in frame.value.columns)
    assert rules["Regla"].tolist() == [f"R{number:02d}" for number in range(1, 25)]
    assert set(rules["Estado"]) == {"Activa"}
    text = " ".join(item.value for item in app.markdown)
    assert "Guía de Atalaya" in text and "Panel" in text and "IA local" in text
