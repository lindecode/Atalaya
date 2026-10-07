from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from infrastructure.sqlite.queries import since_hours
from interfaces.gui.common import CachedQueries, refresh_data
from settings import Settings


class Query:
    def __init__(self, path):
        self.settings = replace(Settings(), database_path=path)
        self.calls = 0

    def rows(self, table, since=None, limit=10):
        self.calls += 1
        return [{"table": table, "since": since, "limit": limit, "n": self.calls}]


def test_window_start_is_rounded_to_the_minute():
    start = datetime.fromisoformat(since_hours(24))
    assert start.second == 0 and start.microsecond == 0


def test_reads_are_cached_per_arguments_until_refreshed(tmp_path):
    refresh_data()
    query = Query(tmp_path / "a.db")
    cached = CachedQueries(query)
    first = cached.rows("alerts", "2026-10-07T00:00:00+00:00")
    assert cached.rows("alerts", "2026-10-07T00:00:00+00:00") == first and query.calls == 1
    cached.rows("alerts", "2026-10-07T00:00:00+00:00", limit=5)
    assert query.calls == 2  # different arguments, different entry
    first[0]["n"] = 99  # callers get copies: mutating one does not poison the cache
    assert cached.rows("alerts", "2026-10-07T00:00:00+00:00")[0]["n"] == 1
    refresh_data()
    cached.rows("alerts", "2026-10-07T00:00:00+00:00")
    assert query.calls == 3
    assert cached.settings is query.settings
