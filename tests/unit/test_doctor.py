from __future__ import annotations

from dataclasses import replace
import sqlite3

from application.doctor import DoctorService
from settings import Settings


class Models:
    def __init__(self, installed=None, error=None, current="qwen3.5:4b"):
        self.installed, self.error, self._current = installed or [], error, current
    def available(self):
        if self.error: raise ConnectionError(self.error)
        return self.installed
    def current(self, role="chat"): return self._current


QWEN = {"name": "qwen3.5:4b", "chat": True, "tools": True, "parameters": "4.7B", "size_gb": 3.4}
EMBED = {"name": "embeddinggemma:latest", "chat": False, "tools": False}


def doctor(tmp_path, models, **probes):
    settings = replace(Settings(), database_path=tmp_path / "data" / "a.db", firewall_log_path=tmp_path / "none.log")
    defaults = dict(find_ollama=lambda: r"C:\Ollama\ollama.exe", security_readable=lambda: (True, ""),
                    sysmon_installed=lambda: False, total_ram_gb=lambda: 32.0, module_available=lambda name: True,
                    disk_free_gb=lambda path: 100.0)
    return {c.id: c for c in DoctorService(settings, models, **{**defaults, **probes}).run()}


def test_everything_present(tmp_path):
    checks = doctor(tmp_path, Models([QWEN, EMBED]))
    assert {checks[k].status for k in ("python", "deps", "data", "ollama", "model-analysis", "model-chat", "model-summary", "model-embed", "security")} == {"ok"}
    assert checks["firewall"].status == "info" and checks["sysmon"].status == "info"   # optional sources


def test_missing_ollama_is_a_warning_with_the_install_command(tmp_path):
    checks = doctor(tmp_path, Models(), find_ollama=lambda: None)
    assert checks["ollama"].status == "warn" and "winget install Ollama.Ollama" in checks["ollama"].fix
    assert "model-chat" not in checks


def test_ollama_installed_but_stopped(tmp_path):
    checks = doctor(tmp_path, Models(error="connection refused"))
    assert checks["ollama"].status == "warn" and "no responde" in checks["ollama"].detail


def test_missing_models_say_how_to_pull_them(tmp_path):
    checks = doctor(tmp_path, Models([]))
    assert checks["model-chat"].status == "warn" and "ollama pull qwen3.5:4b" in checks["model-chat"].fix
    assert checks["model-embed"].status == "info" and "ollama pull embeddinggemma" in checks["model-embed"].fix


def test_model_without_tools_warns_about_chat(tmp_path):
    granite = {"name": "granite4.1:3b", "chat": True, "tools": False}
    checks = doctor(tmp_path, Models([granite, EMBED], current="granite4.1:3b"))
    assert checks["model-chat"].status == "warn" and "herramientas" in checks["model-chat"].detail


def test_missing_dependencies_block(tmp_path):
    checks = doctor(tmp_path, Models([QWEN]), module_available=lambda name: name != "streamlit")
    assert checks["deps"].status == "fail" and "streamlit" in checks["deps"].detail


def test_low_ram_and_low_disk_and_no_security_access(tmp_path):
    checks = doctor(tmp_path, Models([QWEN, EMBED]), total_ram_gb=lambda: 6.0, disk_free_gb=lambda path: 1.0,
                    security_readable=lambda: (False, "Acceso denegado"))
    assert checks["ram"].status == "warn" and "qwen3.5:0.8b" in checks["ram"].fix
    assert checks["data"].status == "warn"
    assert checks["security"].status == "info" and "Configurar permisos" in checks["security"].fix


def test_operation_checks_database_rag_lock_and_backup(tmp_path):
    database = tmp_path / "data" / "a.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE runs(id INTEGER PRIMARY KEY, finished_at TEXT, status TEXT)")
        connection.execute("CREATE TABLE knowledge_chunks(id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO runs(finished_at,status) VALUES ('2026-10-05T12:00:00+00:00','ok')")
        connection.execute("INSERT INTO knowledge_chunks DEFAULT VALUES")
    (database.with_suffix(".cycle.lock")).write_text("123", encoding="ascii")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "atalaya_20261005.db").write_bytes(b"backup")
    settings = replace(Settings(), database_path=database, backup_dir=backup_dir,
                       firewall_log_path=tmp_path / "none.log")
    checks = {item.id: item for item in DoctorService(
        settings, Models([QWEN, EMBED]), find_ollama=lambda: r"C:\Ollama\ollama.exe",
        security_readable=lambda: (True, ""), sysmon_installed=lambda: False,
        total_ram_gb=lambda: 32.0, module_available=lambda name: True,
        disk_free_gb=lambda path: 100.0).run()}
    assert checks["database"].status == "ok"
    assert checks["rag"].status == "ok" and "1 fragmento" in checks["rag"].detail
    assert checks["last-run"].status == "ok"
    assert checks["cycle-lock"].status == "warn"
    assert checks["backup"].status == "ok"
