from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from domain.models import CollectionResult, FileEvent
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


def test_concurrent_watch_writes_and_analysis_reads_do_not_lock(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "concurrent.db", watch_dirs=())
    repository = SQLiteRepository(settings); repository.initialize()
    run_id = repository.start_run("watch", "2026-10-01T12:00:00+00:00", False)

    def write(index):
        event = FileEvent("2026-10-01T12:00:00+00:00", "watchdog", "modified", f"C:/x/{index}", dedup_key=str(index))
        return repository.save_collection(run_id, CollectionResult("watchdog", "file_events", (event,), "ok"), event.ts)

    def read(_):
        return len(repository.load_evidence("2026-10-01T00:00:00+00:00").file_events)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: write(i) if i % 2 else read(i), range(40)))
    assert repository.status()["tables"]["file_events"] == 20
