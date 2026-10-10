from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from domain.models import CollectionResult, FileEvent
from infrastructure.sqlite.queries import SQLiteQueryRepository
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc).isoformat()


def test_duplicates_require_same_hash_at_distinct_current_paths(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "duplicates.db")
    repository = SQLiteRepository(settings)
    repository.initialize()
    run = repository.start_run("collect", NOW, False)
    events = (
        FileEvent(NOW, "scan", "observed_new", r"C:\A\one.bin", size=100, sha256="a" * 64, dedup_key="1"),
        FileEvent(NOW, "scan", "modified", r"C:\A\one.bin", size=100, sha256="a" * 64, dedup_key="2"),
        FileEvent(NOW, "scan", "observed_new", r"C:\B\copy.bin", size=100, sha256="a" * 64, dedup_key="3"),
        FileEvent(NOW, "scan", "observed_new", r"C:\C\unique.bin", size=50, sha256="b" * 64, dedup_key="4"),
        FileEvent(NOW, "scan", "observed_new", r"C:\D\gone.bin", size=100, sha256="a" * 64, dedup_key="5"),
        FileEvent(NOW, "watchdog", "deleted", r"C:\D\gone.bin", dedup_key="6"),
    )
    repository.save_collection(run, CollectionResult("files", "file_events", events, "ok"), NOW)

    duplicates = SQLiteQueryRepository(settings).duplicate_files(NOW)

    assert {row["path"] for row in duplicates} == {r"C:\A\one.bin", r"C:\B\copy.bin"}
    assert {row["sha256"] for row in duplicates} == {"a" * 64}
