from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


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
    database_path: Path = field(default_factory=lambda: Path(os.environ.get("NETWORK_LLM_DB", PROJECT_DIR / "data" / "network_llm.db")))
    reports_dir: Path = field(default_factory=lambda: Path(os.environ.get("NETWORK_LLM_REPORTS", PROJECT_DIR / "reports")))
    backup_dir: Path = PROJECT_DIR / "data" / "backups"
    watch_dirs: tuple[Path, ...] = field(default_factory=_default_watch_dirs)
    scan_hours: int = 24
    hash_max_bytes: int = 50 * 1024 * 1024
    sqlite_busy_timeout_ms: int = 5_000
    retention_days: int = 30
    baseline_runs: int = 5
    rule_window_hours: int = 24
    brute_force_count: int = 10
    brute_force_minutes: int = 5
    mass_file_count: int = 100
    mass_file_minutes: int = 1
    anomalous_extension_count: int = 20
    port_scan_count: int = 20
    suspicious_ports: tuple[int, ...] = (4444, 1337, 31337, 6667, 5555, 9001)
    ollama_host: str = field(default_factory=lambda: os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    ollama_model: str = "qwen3.5:4b"
    llm_timeout_seconds: float = 60.0

    def ensure_runtime_dirs(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def validated_ollama_host(self) -> str:
        parsed = urlparse(self.ollama_host)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("OLLAMA_HOST debe apuntar exactamente a localhost, 127.0.0.1 o ::1")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OLLAMA_HOST no admite credenciales, query ni fragmento")
        return self.ollama_host.rstrip("/")
