from __future__ import annotations

from dataclasses import replace

from domain.reputation import ReputationResult
from infrastructure.sqlite.reputation_store import SQLiteReputationStore
from settings import Settings


def test_reputation_upsert_and_read(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "reputation.db", reports_dir=tmp_path / "reports")
    store = SQLiteReputationStore(settings); store.initialize()
    first = ReputationResult("a" * 64, "x.exe", "2026-10-02T00:00:00+00:00", {}, "local", None,
                             "unknown", 0.25, ("sin datos",))
    second = ReputationResult("a" * 64, "x.exe", "2026-10-02T01:00:00+00:00", {}, "local", None,
                              "likely_safe", 0.8, ("validado",))
    store.save(first); store.save(second)
    rows = store.latest()
    assert len(rows) == 1
    assert rows[0]["verdict"] == "likely_safe"
