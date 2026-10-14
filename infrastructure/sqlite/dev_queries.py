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

    def ssh_history(self, since: str) -> list[dict]:
        """SSH sessions with a remote end seen in the window, one row per peer and direction."""
        with connect(self.settings.database_path, self.settings.sqlite_busy_timeout_ms, readonly=True) as db:
            return [dict(row) for row in db.execute(
                """SELECT remote_address, remote_port, direction, MAX(process_name) process_name,
                          GROUP_CONCAT(DISTINCT tunnel_types) tunnel_types, MAX(COALESCE(agent_forwarding, 0)) agent_forwarding,
                          CASE WHEN direction='inbound' THEN local_port END local_port,
                          MIN(ts) first_seen, MAX(ts) last_seen, COUNT(*) observations
                   FROM ssh_observations WHERE kind='session' AND ts>=? AND remote_address IS NOT NULL
                   GROUP BY remote_address, remote_port, direction, CASE WHEN direction='inbound' THEN local_port END
                   ORDER BY last_seen DESC""", (since,))]
