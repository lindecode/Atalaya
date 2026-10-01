from __future__ import annotations

import queue
import time
from datetime import datetime, timedelta

from domain.models import CollectionResult
from domain.rules.catalog import r08, r09


class WatchService:
    def __init__(self, repository, clock, system_info, notifier, settings):
        self.repository = repository
        self.clock = clock
        self.system_info = system_info
        self.notifier = notifier
        self.settings = settings

    def _flush(self, run_id: int, events: list) -> tuple[int, int]:
        if not events: return 0, 0
        result = CollectionResult("watchdog", "file_events", tuple(events), "ok")
        inserted = self.repository.save_collection(run_id, result, self.clock.now_iso())
        since = (datetime.fromisoformat(self.clock.now_iso()) - timedelta(minutes=2)).isoformat()
        view = self.repository.load_evidence(since)
        candidates = r08(view, self.settings) + r09(view, self.settings)
        alert_ids = self.repository.save_alerts(candidates)
        for candidate in candidates:
            if candidate.severity in {"high", "critical"}:
                self.notifier.notify(candidate.title, str(candidate.summary))
        return inserted, len(alert_ids)

    def execute(self) -> dict[str, int]:
        from watchdog.observers import Observer
        from infrastructure.windows.file_watcher import QueueingEventHandler

        self.repository.initialize()
        run_id = self.repository.start_run("watch", self.clock.now_iso(), self.system_info.is_admin())
        events = queue.Queue()
        handler = QueueingEventHandler(events)
        observer = Observer()
        watched = 0
        for path in self.settings.watch_dirs:
            if path.exists():
                observer.schedule(handler, str(path), recursive=True)
                watched += 1
        if not watched:
            self.repository.finish_run(run_id, self.clock.now_iso(), "error", {"watchdog": {"status": "error", "warnings": ["No hay carpetas disponibles"]}})
            return {"run_id": run_id, "events": 0, "alerts": 0}
        total = alerts = 0
        observer.start()
        try:
            while True:
                time.sleep(self.settings.watch_batch_seconds)
                batch = []
                while True:
                    try: batch.append(events.get_nowait())
                    except queue.Empty: break
                inserted, new_alerts = self._flush(run_id, batch)
                total += inserted; alerts += new_alerts
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop(); observer.join(timeout=10)
            batch = []
            while True:
                try: batch.append(events.get_nowait())
                except queue.Empty: break
            inserted, new_alerts = self._flush(run_id, batch)
            total += inserted; alerts += new_alerts
            self.repository.finish_run(run_id, self.clock.now_iso(), "ok", {"watchdog": {"status": "ok", "inserted": total}})
        return {"run_id": run_id, "events": total, "alerts": alerts}

