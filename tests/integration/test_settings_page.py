from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from infrastructure.sqlite.repositories import SQLiteRepository
from infrastructure.windows import system_features
from settings import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def fake_system(tmp_path, monkeypatch):
    """Ajustes against fake Windows features: the test never creates tasks or shortcuts on this machine."""
    database = tmp_path / "settings.db"
    monkeypatch.setenv("ATALAYA_DB", str(database))
    monkeypatch.setenv("ATALAYA_REPORTS", str(tmp_path / "reports"))
    SQLiteRepository(replace(Settings(), database_path=database)).initialize()
    state = {"cycle": False, "startup": True, "calls": []}

    def set_cycle(enabled, minutes=5):
        state["calls"].append(("cycle", enabled, minutes))
        state["cycle"] = enabled
        return True, "ok"

    monkeypatch.setattr(system_features, "cycle_task_status",
                        lambda: {"enabled": state["cycle"], "minutes": 5, "windowless": True, "next": None})
    monkeypatch.setattr(system_features, "set_cycle_task", set_cycle)
    monkeypatch.setattr(system_features, "startup_enabled", lambda: state["startup"])
    monkeypatch.setattr(system_features, "set_startup",
                        lambda enabled: state["calls"].append(("startup", enabled)) or (True, "ok"))
    monkeypatch.setattr(system_features, "file_monitor_running", lambda: False)
    from interfaces.gui import page_views
    page_views._cycle_task.clear()
    return state


def test_switches_show_the_real_state_and_change_it(fake_system):
    app = AppTest.from_file(ROOT / "interfaces/gui/views/32_Ajustes.py", default_timeout=30).run()
    assert not app.exception
    assert any("Desactivado" in element.value for element in app.markdown)

    app.toggle(key="feature-cycle-False").set_value(True).run()
    assert fake_system["calls"] == [("cycle", True, 5)]
    assert not app.exception
    assert app.toggle(key="feature-cycle-True").value is True  # re-read from the (fake) system

    # The fake startup script reports success but changes nothing: the action runs once, no endless reruns
    app.toggle(key="feature-startup-True").set_value(False).run()
    assert not app.exception
    assert fake_system["calls"].count(("startup", False)) == 1
    assert app.toggle(key="feature-startup-True").value is True  # still the real state


def test_ai_switches_are_saved_in_the_cycle_configuration(fake_system):
    from bootstrap import build_automation_config_service

    app = AppTest.from_file(ROOT / "interfaces/gui/views/32_Ajustes.py", default_timeout=30).run()
    app.toggle(key="feature-llm-True").set_value(False).run()
    assert not app.exception
    config = build_automation_config_service().load()
    assert config.use_llm is False and config.section_summaries is True
    assert app.toggle(key="feature-summaries-True").disabled  # summaries need the AI switch
