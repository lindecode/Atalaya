from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent


def _default_watch_dirs() -> tuple[Path, ...]:
    profile = Path(os.environ.get("USERPROFILE", Path.home()))
    candidates = (
        profile / "Desktop",
        profile / "Documents",
        profile / "Downloads",
        profile / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup",
        Path(os.environ.get("TEMP", profile / "AppData/Local/Temp")),
    )
    return tuple(path.resolve() for path in candidates)


@dataclass(frozen=True, slots=True)
class Settings:
    project_dir: Path = PROJECT_DIR
    database_path: Path = PROJECT_DIR / "data" / "network_llm.db"
    reports_dir: Path = PROJECT_DIR / "reports"
    backup_dir: Path = PROJECT_DIR / "data" / "backups"
    watch_dirs: tuple[Path, ...] = field(default_factory=_default_watch_dirs)
    scan_hours: int = 24
    hash_max_bytes: int = 50 * 1024 * 1024
    sqlite_busy_timeout_ms: int = 5_000
    retention_days: int = 30

    def ensure_runtime_dirs(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

