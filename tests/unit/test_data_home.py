from __future__ import annotations

import sqlite3

import settings
from shared.legacy_data import migrate_legacy_data


def test_data_lives_outside_the_program_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("ATALAYA_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(settings, "PROJECT_DIR", tmp_path / "app")
    assert settings.data_home() == tmp_path / "local" / "Atalaya"


def test_atalaya_home_and_portable_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PROJECT_DIR", tmp_path / "app")
    (tmp_path / "app").mkdir()
    monkeypatch.setenv("ATALAYA_HOME", str(tmp_path / "custom"))
    assert settings.data_home() == tmp_path / "custom"
    monkeypatch.delenv("ATALAYA_HOME")
    (tmp_path / "app" / "portable").write_text("", encoding="utf-8")
    assert settings.data_home() == tmp_path / "app" / "userdata"


def test_legacy_database_and_reports_are_copied_once(tmp_path):
    project = tmp_path / "app"
    (project / "data").mkdir(parents=True)
    (project / "reports").mkdir()
    with sqlite3.connect(project / "data" / "network_llm.db") as db:
        db.execute("CREATE TABLE alerts(id INTEGER)"); db.execute("INSERT INTO alerts VALUES (7)")
    (project / "reports" / "20261001_1943.md").write_text("# informe", encoding="utf-8")
    target_db = tmp_path / "home" / "data" / "atalaya.db"

    moved = migrate_legacy_data(project, target_db, tmp_path / "home" / "reports")

    assert len(moved) == 2
    with sqlite3.connect(target_db) as db:
        assert db.execute("SELECT id FROM alerts").fetchone()[0] == 7
    assert (tmp_path / "home" / "reports" / "20261001_1943.md").exists()
    assert (target_db.parent / "MIGRADO_DESDE.txt").exists()
    assert (project / "data" / "network_llm.db").exists()          # originals are kept
    assert migrate_legacy_data(project, target_db, tmp_path / "home" / "reports") == []  # never twice


def test_only_the_default_location_inherits_old_data(monkeypatch, tmp_path):
    from dataclasses import replace

    project = tmp_path / "app"
    (project / "data").mkdir(parents=True)
    sqlite3.connect(project / "data" / "atalaya.db").close()
    monkeypatch.setattr(settings, "PROJECT_DIR", project)
    monkeypatch.setenv("ATALAYA_HOME", str(tmp_path / "home"))
    explicit = replace(settings.Settings(), project_dir=project, database_path=tmp_path / "test.db")
    explicit.ensure_runtime_dirs()
    assert not (tmp_path / "test.db").exists()                     # a test database stays empty
    default = replace(settings.Settings(), project_dir=project)
    default.ensure_runtime_dirs()
    assert default.database_path == tmp_path / "home" / "data" / "atalaya.db" and default.database_path.exists()


def test_firewall_log_follows_configurar_permisos_including_the_old_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("ATALAYA_FIREWALL_LOG", raising=False)
    monkeypatch.setenv("ProgramData", str(tmp_path))
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    assert settings._default_firewall_log().name == "pfirewall.log" and "System32" in str(settings._default_firewall_log())
    legacy = tmp_path / "network-llm" / "firewall" / "pfirewall.log"
    legacy.parent.mkdir(parents=True); legacy.write_text("", encoding="utf-8")
    assert settings._default_firewall_log() == legacy
    current = tmp_path / "Atalaya" / "firewall" / "pfirewall.log"
    current.parent.mkdir(parents=True); current.write_text("", encoding="utf-8")
    assert settings._default_firewall_log() == current
