# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from domain.reputation import ReputationResult
from settings import Settings


class ReputationService:
    calls = []

    def inspect(self, path, online=False):
        self.calls.append((path, online))
        return ReputationResult("a" * 64, str(path), "2026-10-09T18:30:00+00:00",
                                {"signature": {"status": "Valid", "valid": True}}, "local", None,
                                "unknown", 0.45, ("Firma válida",))


def test_reputation_is_available_in_gui_without_cli_command(tmp_path, monkeypatch):
    ReputationService.calls.clear()
    settings = Settings(database_path=tmp_path / "atalaya.db", reports_dir=tmp_path / "reports")
    monkeypatch.setattr("interfaces.gui.common.Settings", lambda: settings)
    monkeypatch.setattr("bootstrap.build_reputation_service", lambda configured=None: ReputationService())
    page = Path(__file__).resolve().parents[2] / "interfaces" / "gui" / "views" / "14_Archivos.py"

    app = AppTest.from_file(page).run(timeout=20)
    app.text_input(key="reputation-path").set_value(str(tmp_path / "sample.exe"))
    next(item for item in app.button if item.label == "Analizar archivo").click().run(timeout=20)

    assert ReputationService.calls == [(tmp_path / "sample.exe", False)]
    assert any("a" * 64 in item.value for item in app.code)
    assert not any("reputation inspect" in item.value for item in app.markdown)


def test_online_reputation_requires_explicit_key(tmp_path, monkeypatch):
    ReputationService.calls.clear()
    settings = Settings(database_path=tmp_path / "atalaya.db", reports_dir=tmp_path / "reports")
    monkeypatch.setattr("interfaces.gui.common.Settings", lambda: settings)
    monkeypatch.setattr("bootstrap.build_reputation_service", lambda configured=None: ReputationService())
    page = Path(__file__).resolve().parents[2] / "interfaces" / "gui" / "views" / "14_Archivos.py"

    app = AppTest.from_file(page).run(timeout=20)
    app.text_input(key="reputation-path").set_value(str(tmp_path / "sample.exe"))
    app.checkbox(key="reputation-online").check()
    next(item for item in app.button if item.label == "Analizar archivo").click().run(timeout=20)

    assert not ReputationService.calls
    assert any("clave API" in item.value for item in app.error)
