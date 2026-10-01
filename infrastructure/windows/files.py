from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from domain.models import CollectionRequest, CollectionResult, FileEvent
from settings import Settings
from shared.paths import normalized_windows_path


HASH_EXTENSIONS = {".exe", ".dll", ".ps1", ".bat", ".cmd", ".vbs", ".js", ".hta", ".scr", ".lnk", ".msi"}
EXCLUDED_PARTS = {".git", "node_modules", "__pycache__", ".venv", "cache", "caches", "code cache"}


def _sha256(path: Path, max_bytes: int) -> str | None:
    before = path.stat()
    if before.st_size > max_bytes:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError("el archivo cambió durante el cálculo del hash")
    return digest.hexdigest()


class RecentFileCollector:
    name = "recent_files"

    def __init__(self, settings: Settings):
        self.settings = settings

    def collect(self, request: CollectionRequest) -> CollectionResult:
        now = datetime.fromisoformat(request.now)
        cutoff = now - timedelta(hours=self.settings.scan_hours)
        items: list[FileEvent] = []
        warnings: list[str] = []

        for root in self.settings.watch_dirs:
            if not root.exists():
                warnings.append(f"Carpeta inexistente: {root}")
                continue
            for current, dirs, files in os.walk(root, topdown=True, onerror=lambda exc: warnings.append(str(exc))):
                current_path = Path(current)
                kept_dirs: list[str] = []
                for directory in dirs:
                    candidate = current_path / directory
                    is_junction = getattr(candidate, "is_junction", lambda: False)()
                    if directory.casefold() not in EXCLUDED_PARTS and not candidate.is_symlink() and not is_junction:
                        kept_dirs.append(directory)
                dirs[:] = kept_dirs
                for filename in files:
                    path = current_path / filename
                    try:
                        stat = path.stat()
                        modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                        if modified < cutoff:
                            continue
                        created = datetime.fromtimestamp(stat.st_ctime, timezone.utc)
                        action = "observed_new" if created >= cutoff else "observed_changed"
                        extension = path.suffix.casefold()
                        file_hash = _sha256(path, self.settings.hash_max_bytes) if extension in HASH_EXTENSIONS else None
                        key_source = f"{normalized_windows_path(path)}|{stat.st_mtime_ns}|{stat.st_size}"
                        items.append(FileEvent(
                            ts=modified.isoformat(), source="scan", action=action, path=str(path),
                            extension=extension or None, size=stat.st_size, sha256=file_hash,
                            dedup_key=hashlib.sha256(key_source.encode("utf-8")).hexdigest(),
                        ))
                    except (OSError, PermissionError) as exc:
                        warnings.append(f"{path}: {exc}")
        return CollectionResult(self.name, "file_events", tuple(items), "ok", tuple(warnings))

