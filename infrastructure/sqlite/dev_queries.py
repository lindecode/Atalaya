from __future__ import annotations

from infrastructure.sqlite.connection import connect


class SQLiteDevQueries:
    """History of the listening sockets each collection saw, for the Desarrollo timeline."""

    def __init__(self, settings):
        self.settings = settings

    def listen_history(self, since: str) -> dict:
        """Every collection time in the window, and the listening (port, process) pairs seen at each one."""
        with connect(self.settings.database_path, self.settings.sqlite_busy_timeout_ms, readonly=True) as db:
            snapshots = [row[0] for row in db.execute(
                "SELECT DISTINCT ts FROM connections WHERE direction='listen' AND ts>=? ORDER BY ts", (since,))]
            rows = [dict(row) for row in db.execute(
                """SELECT DISTINCT ts, lport, process_name, process_path, laddr FROM connections
                   WHERE direction='listen' AND ts>=? ORDER BY ts""", (since,))]
        return {"snapshots": snapshots, "rows": rows}
