"""One-time move of user data from the program folder (older versions) to the data home.

Older versions kept data\\ and reports\\ inside the program folder, where an update or uninstall could wipe
them. The first run of a newer version copies them to the data home. The old copies are left untouched
(the program folder may be read-only) and a note in the data home records where they came from.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

LEGACY_DB_NAMES = ("atalaya.db", "network_llm.db")
NOTE = "MIGRADO_DESDE.txt"


def migrate_legacy_data(project_dir: Path, database_path: Path, reports_dir: Path) -> list[str]:
    """Copies legacy data next to `database_path` when that database does not exist yet. Returns what moved."""
    moved: list[str] = []
    legacy_data = project_dir / "data"
    if database_path.exists() or legacy_data.resolve() == database_path.parent.resolve():
        return moved
    source = next((legacy_data / name for name in LEGACY_DB_NAMES if (legacy_data / name).is_file()), None)
    if source is not None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        # The backup API gives a consistent copy even if the old database still has a WAL file
        with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as old, sqlite3.connect(database_path) as new:
            old.backup(new)
        moved.append(str(source))
    legacy_reports = project_dir / "reports"
    if legacy_reports.is_dir() and legacy_reports.resolve() != reports_dir.resolve():
        reports_dir.mkdir(parents=True, exist_ok=True)
        for report in legacy_reports.glob("*.md"):
            if not (reports_dir / report.name).exists():
                shutil.copy2(report, reports_dir / report.name)
                moved.append(str(report))
    if moved:
        (database_path.parent / NOTE).write_text(
            "Datos copiados desde una versión anterior de Atalaya (los originales no se borraron):\n"
            + "\n".join(moved) + "\n", encoding="utf-8")
    return moved
