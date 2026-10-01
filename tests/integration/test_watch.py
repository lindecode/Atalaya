from __future__ import annotations

from dataclasses import replace

from application.watch import WatchService
from domain.models import FileEvent
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


class Clock:
    def now_iso(self): return "2026-10-01T12:01:00+00:00"


class System:
    def is_admin(self): return False


class Notifier:
    def __init__(self): self.messages = []
    def notify(self, title, message): self.messages.append((title, message))


def test_watch_batch_triggers_r08_and_uses_single_batch(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "watch.db", watch_dirs=(), mass_file_count=100)
    repository = SQLiteRepository(settings); repository.initialize()
    run_id = repository.start_run("watch", Clock().now_iso(), False)
    notifier = Notifier()
    service = WatchService(repository, Clock(), System(), notifier, settings)
    events = [FileEvent(f"2026-10-01T12:00:{i // 2:02d}+00:00", "watchdog", "modified", f"C:/x/{i}.txt", dedup_key=str(i)) for i in range(100)]

    inserted, alerts = service._flush(run_id, events)

    assert inserted == 100
    assert alerts >= 1
    assert notifier.messages

