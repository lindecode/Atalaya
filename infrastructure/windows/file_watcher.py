from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from domain.models import FileEvent


def _event(action: str, path: str, dest_path: str | None = None) -> FileEvent:
    now = datetime.now(timezone.utc).isoformat()
    target = Path(path)
    size = None
    if action not in {"deleted", "moved"}:
        try: size = target.stat().st_size
        except OSError: pass
    key = hashlib.sha256(f"{action}|{path}|{dest_path}|{now}".encode("utf-8")).hexdigest()
    # a rename's interesting extension is the new one (photo.jpg -> photo.jpg.locked)
    extension = Path(dest_path).suffix if action == "moved" and dest_path else target.suffix
    return FileEvent(now, "watchdog", action, path, dest_path, extension.casefold() or None, size, dedup_key=key)


def build_observer(paths, output_queue):
    """watchdog Observer feeding FileEvents into `output_queue`; returns (observer, folders watched)."""
    from watchdog.observers import Observer
    handler, observer, watched = QueueingEventHandler(output_queue), Observer(), 0
    for path in paths:
        if path.exists():
            observer.schedule(handler, str(path), recursive=True)
            watched += 1
    return observer, watched


class QueueingEventHandler:
    def __init__(self, output_queue):
        from watchdog.events import FileSystemEventHandler
        self._delegate = FileSystemEventHandler()
        self.output_queue = output_queue

    def dispatch(self, event):
        if event.is_directory: return
        mapping = {"created": "created", "modified": "modified", "deleted": "deleted", "moved": "moved"}
        action = mapping.get(event.event_type)
        if action:
            self.output_queue.put(_event(action, event.src_path, getattr(event, "dest_path", None)))

