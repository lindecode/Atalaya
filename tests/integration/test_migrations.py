from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from infrastructure.sqlite.migrations import MIGRATIONS
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


def _repository(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "m.db", reports_dir=tmp_path / "r")
    return settings.database_path, SQLiteRepository(settings)


def _version(path):
    with sqlite3.connect(path) as db:
        return db.execute("PRAGMA user_version").fetchone()[0]


def test_fresh_database_reaches_latest_version_and_is_idempotent(tmp_path):
    path, repository = _repository(tmp_path)
    repository.initialize()
    repository.initialize()
    assert _version(path) == len(MIGRATIONS)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("applied", range(1, len(MIGRATIONS)))
def test_every_intermediate_version_upgrades_to_latest(tmp_path, applied):
    path, repository = _repository(tmp_path)
    with sqlite3.connect(path) as db:
        for index, sql in enumerate(MIGRATIONS[:applied], start=1):
            db.executescript(sql); db.execute(f"PRAGMA user_version={index}")
    repository.initialize()
    assert _version(path) == len(MIGRATIONS)


def test_future_version_is_rejected(tmp_path):
    path, repository = _repository(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version={len(MIGRATIONS) + 1}")
    with pytest.raises(RuntimeError, match="versión futura"):
        repository.initialize()
