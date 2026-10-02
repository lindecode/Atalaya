from __future__ import annotations

from dataclasses import replace

from domain.models import CollectionResult, FileEvent, PersistenceItem, SSHObservation
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


NOW = "2026-10-01T12:00:00+00:00"


def make_repository(tmp_path):
    settings = replace(
        Settings(), database_path=tmp_path / "atalaya.db",
        reports_dir=tmp_path / "reports", backup_dir=tmp_path / "backups", watch_dirs=(),
    )
    repository = SQLiteRepository(settings)
    repository.initialize()
    return repository


def test_migration_and_file_event_idempotence(tmp_path):
    repository = make_repository(tmp_path)
    repository.initialize()
    run_id = repository.start_run("collect", NOW, False)
    event = FileEvent(NOW, "scan", "observed_new", r"C:\Users\me\a.ps1", extension=".ps1", size=1, dedup_key="stable")
    result = CollectionResult("files", "file_events", (event,), "ok")

    assert repository.save_collection(run_id, result, NOW) == 1
    assert repository.save_collection(run_id, result, NOW) == 0
    assert repository.status()["tables"]["file_events"] == 1


def test_persistence_upsert_preserves_first_seen_and_counts_only_new(tmp_path):
    repository = make_repository(tmp_path)
    run_id = repository.start_run("collect", NOW, False)
    item = PersistenceItem(NOW, NOW, "run_key", r"HKCU\Run", "Agent", "agent.exe")
    result = CollectionResult("persistence", "persistence_items", (item,), "ok")

    assert repository.save_collection(run_id, result, NOW) == 1
    assert repository.save_collection(run_id, result, "2026-10-02T12:00:00+00:00") == 0
    assert repository.status()["tables"]["persistence_items"] == 1


def test_ssh_observation_is_idempotent(tmp_path):
    repository = make_repository(tmp_path)
    run_id = repository.start_run("collect", NOW, False)
    item = SSHObservation(NOW, "session", "outbound", "10.0.0.2", 50000, "203.0.113.8", 2222,
                          "ESTABLISHED", 42, "ssh.exe", r"C:\Windows\ssh.exe", "alice",
                          "ssh.exe -R", "reverse", False, None, None, "ssh-stable")
    result = CollectionResult("ssh", "ssh_observations", (item,), "ok")
    assert repository.save_collection(run_id, result, NOW) == 1
    assert repository.save_collection(run_id, result, NOW) == 0
    assert repository.status()["tables"]["ssh_observations"] == 1


def test_cursor_is_saved_with_collection(tmp_path):
    repository = make_repository(tmp_path)
    run_id = repository.start_run("collect", NOW, True)
    result = CollectionResult("security", "auth_events", (), "ok", next_cursor={"record_id": 100})
    repository.save_collection(run_id, result, NOW)
    assert repository.get_cursor("security") == {"record_id": 100}


def test_backup_and_purge_preserve_confirmed_alert_snapshot(tmp_path):
    from domain.models import AlertCandidate, EvidenceRef
    repository = make_repository(tmp_path)
    alert_id = repository.save_alerts([AlertCandidate(
        "2020-01-01T00:00:00+00:00", "R13", "critical", "Borrado", "security",
        {}, (EvidenceRef("auth_event", 99, {"id": 99, "event_id": 1102}),), "old",
    )])[0]
    repository.update_alert_status(alert_id, "confirmed", None, NOW)
    destination = tmp_path / "backup.db"
    assert repository.backup(destination).exists()
    repository.purge("2025-01-01T00:00:00+00:00")
    alerts = repository.get_alerts()
    assert alerts[0]["id"] == alert_id
    assert alerts[0]["status"] == "confirmed"
    assert repository.get_new_alerts() == []
