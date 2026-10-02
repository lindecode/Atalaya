from __future__ import annotations

import json
from dataclasses import asdict

from domain.reputation import ReputationResult
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.migrations import MIGRATIONS


class SQLiteReputationStore:
    def __init__(self, settings): self.settings = settings

    def _connect(self, readonly=False):
        return connect(self.settings.database_path, self.settings.sqlite_busy_timeout_ms, readonly=readonly)

    def initialize(self):
        self.settings.ensure_runtime_dirs()
        with self._connect() as db:
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            for index in range(version, len(MIGRATIONS)):
                db.executescript(MIGRATIONS[index]); db.execute(f"PRAGMA user_version={index + 1}")

    def save(self, result: ReputationResult):
        value = asdict(result)
        with self._connect() as db:
            db.execute("""INSERT INTO file_reputation
                (sha256,path,checked_at,local_json,provider,external_json,verdict,confidence,reasons_json)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(sha256,provider) DO UPDATE SET
                path=excluded.path, checked_at=excluded.checked_at, local_json=excluded.local_json,
                external_json=excluded.external_json, verdict=excluded.verdict,
                confidence=excluded.confidence, reasons_json=excluded.reasons_json""",
                (result.sha256, result.path, result.checked_at, json.dumps(value["local"], ensure_ascii=False),
                 result.provider, json.dumps(value["external"], ensure_ascii=False) if result.external is not None else None,
                 result.verdict, result.confidence, json.dumps(value["reasons"], ensure_ascii=False)))

    def latest(self, limit=100):
        with self._connect(readonly=True) as db:
            return [dict(row) for row in db.execute("""SELECT id,sha256,path,checked_at,provider,verdict,confidence,reasons_json
                FROM file_reputation ORDER BY checked_at DESC LIMIT ?""", (min(max(limit, 1), 1000),))]
