from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: Path, busy_timeout_ms: int = 5_000, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    if not readonly:
        connection.execute("PRAGMA journal_mode=WAL")
    return connection

