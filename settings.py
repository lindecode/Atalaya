from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


PROJECT_DIR = Path(__file__).resolve().parent
LEGACY_FIREWALL_DIRS = ("Atalaya", "network-llm")  # %ProgramData% subfolders used by configurar-permisos, newest first


def data_home() -> Path:
    """Where user data lives, separate from the program so installs and updates never touch it.

    ATALAYA_HOME wins; a file named `portable` next to the program keeps data beside it (USB / ZIP use);
    otherwise %LOCALAPPDATA%\\Atalaya.
    """
    if os.environ.get("ATALAYA_HOME"):
        return Path(os.environ["ATALAYA_HOME"])
    if (PROJECT_DIR / "portable").exists():
        return PROJECT_DIR / "userdata"
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Atalaya"


def _default_firewall_log() -> Path:
    """Explicit setting, then the log configured by configurar-permisos (current or legacy folder), else Windows'."""
    if os.environ.get("ATALAYA_FIREWALL_LOG"):
        return Path(os.environ["ATALAYA_FIREWALL_LOG"])
    program_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    for folder in LEGACY_FIREWALL_DIRS:
        candidate = program_data / folder / "firewall" / "pfirewall.log"
        if candidate.exists():
            return candidate
    return Path(os.path.expandvars(r"%SystemRoot%\System32\LogFiles\Firewall\pfirewall.log"))


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
    database_path: Path = field(default_factory=lambda: Path(os.environ.get("ATALAYA_DB", data_home() / "data" / "atalaya.db")))
    reports_dir: Path = field(default_factory=lambda: Path(os.environ.get("ATALAYA_REPORTS", data_home() / "reports")))
    backup_dir: Path = field(default_factory=lambda: data_home() / "data" / "backups")
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
    mass_file_exclude_dirs: tuple[Path, ...] = field(default_factory=lambda: (Path(os.environ.get("TEMP", Path.home() / "AppData/Local/Temp")).resolve(),))
    anomalous_extension_count: int = 20
    port_scan_count: int = 20
    suspicious_ports: tuple[int, ...] = (4444, 1337, 31337, 6667, 5555, 9001)
    ollama_host: str = field(default_factory=lambda: os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    ollama_model: str = "qwen3.5:4b"
    ollama_embedding_model: str = field(default_factory=lambda: os.environ.get("OLLAMA_EMBEDDING_MODEL", "embeddinggemma:latest"))
    llm_timeout_seconds: float = 60.0
    llm_max_alerts: int = 40      # per analyze run; the rest stay 'new' for the next run
    llm_batch_size: int = 8
    rag_chunk_chars: int = 2_800
    rag_chunk_overlap_chars: int = 300
    rag_top_k: int = 6
    rag_max_context_chars: int = 16_000
    virustotal_api_key: str | None = field(default_factory=lambda: os.environ.get("VIRUSTOTAL_API_KEY"))
    reputation_timeout_seconds: float = 15.0
    reputation_max_bytes: int = 50 * 1024 * 1024
    firewall_log_path: Path = field(default_factory=_default_firewall_log)
    watch_batch_seconds: float = 5.0

    def ensure_runtime_dirs(self) -> None:
        # Only the default location inherits old data; tests and ATALAYA_DB point elsewhere on purpose
        if not self.database_path.exists() and self.database_path == data_home() / "data" / "atalaya.db":
            from shared.legacy_data import migrate_legacy_data
            migrate_legacy_data(self.project_dir, self.database_path, self.reports_dir)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def validated_ollama_host(self) -> str:
        parsed = urlparse(self.ollama_host)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("OLLAMA_HOST debe apuntar exactamente a localhost, 127.0.0.1 o ::1")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OLLAMA_HOST no admite credenciales, query ni fragmento")
        return self.ollama_host.rstrip("/")
