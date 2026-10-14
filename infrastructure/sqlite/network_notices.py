from __future__ import annotations

from dataclasses import astuple
from datetime import datetime, timedelta, timezone

from application.network_watch import Notice
from infrastructure.sqlite.connection import connect

KEEP_DAYS = 30


class SQLiteNetworkNotices:
    """Notices raised by the live network watch, for the Desarrollo page."""

    def __init__(self, settings):
        self.settings = settings

    def _connect(self, readonly: bool = False):
        return connect(self.settings.database_path, self.settings.sqlite_busy_timeout_ms, readonly)

    def add(self, notices: list[Notice]) -> None:
        if not notices:
            return
        with self._connect() as db:
            db.executemany("""INSERT INTO network_notices(ts, kind, network, remote_ip, lport, process_name, detail)
                              VALUES (?, ?, ?, ?, ?, ?, ?)""", [astuple(notice) for notice in notices])

    def recent(self, since: str, limit: int = 500) -> list[dict]:
        with self._connect(readonly=True) as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM network_notices WHERE ts>=? ORDER BY ts DESC LIMIT ?", (since, int(limit)))]

    def prune(self, keep_days: int = KEEP_DAYS) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        with self._connect() as db:
            return db.execute("DELETE FROM network_notices WHERE ts<?", (cutoff,)).rowcount
