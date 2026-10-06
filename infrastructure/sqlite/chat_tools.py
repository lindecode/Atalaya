from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from infrastructure.sqlite.connection import connect


def _since(value: str | None) -> str:
    now = datetime.now(timezone.utc)
    mapping = {"1h": 1, "24h": 24, "7d": 168, "30d": 720, "week": 168, "semana": 168}
    if not value: return (now - timedelta(hours=24)).isoformat()
    if value in mapping: return (now - timedelta(hours=mapping[value])).isoformat()
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()


class SQLiteQueryTools:
    def __init__(self, settings): self.settings = settings

    def _query(self, sql, params):
        with connect(self.settings.database_path, readonly=True) as db:
            rows = [dict(row) for row in db.execute(sql + " LIMIT 200", tuple(params))]
        # raw_xml and long command lines would flood the model's context window
        return [{key: (value[:300] if isinstance(value, str) else value) for key, value in row.items() if key != "raw_xml"}
                for row in rows]

    def call(self, name: str, args: dict[str, Any]):
        since = _since(args.get("since"))
        if name == "get_alerts":
            sql, params = "SELECT * FROM alerts WHERE ts>=?", [since]
            if args.get("severity"): sql += " AND severity=?"; params.append(args["severity"])
        elif name == "get_auth_events":
            sql, params = "SELECT * FROM auth_events WHERE ts>=?", [since]
            if args.get("event_id") is not None: sql += " AND event_id=?"; params.append(int(args["event_id"]))
            if args.get("source_ip"): sql += " AND source_ip=?"; params.append(args["source_ip"])
        elif name == "get_connections":
            sql, params = "SELECT * FROM connections WHERE ts>=?", [since]
            if args.get("process"): sql += " AND process_name LIKE ?"; params.append(f"%{args['process']}%")
            if args.get("remote_ip"): sql += " AND raddr=?"; params.append(args["remote_ip"])
        elif name == "get_processes":
            sql, params = """SELECT s.id,s.ts,s.pid,s.name,s.path,s.process_user,s.status,s.parent_name,
                s.rss_bytes,s.private_bytes,s.memory_percent,s.cpu_seconds,s.thread_count,l.first_seen,l.last_seen,
                l.ended_at,l.active,l.peak_rss_bytes,l.peak_private_bytes
                FROM process_snapshots s JOIN process_lifecycle l ON l.process_key=s.process_key
                WHERE s.ts>=?""", [since]
            if args.get("process"): sql += " AND s.name LIKE ?"; params.append(f"%{args['process']}%")
            if args.get("active") is not None: sql += " AND l.active=?"; params.append(int(bool(args["active"])))
        elif name == "get_file_events":
            sql, params = "SELECT * FROM file_events WHERE ts>=?", [since]
            if args.get("path_contains"): sql += " AND path LIKE ?"; params.append(f"%{args['path_contains']}%")
            if args.get("action"): sql += " AND action=?"; params.append(args["action"])
        elif name == "get_file_reputation":
            sql, params = "SELECT * FROM file_reputation WHERE checked_at>=?", [since]
            if args.get("sha256"): sql += " AND sha256=?"; params.append(args["sha256"].casefold())
            if args.get("path_contains"): sql += " AND path LIKE ?"; params.append(f"%{args['path_contains']}%")
            if args.get("verdict"): sql += " AND verdict=?"; params.append(args["verdict"])
        elif name == "get_ssh_observations":
            sql, params = "SELECT * FROM ssh_observations WHERE ts>=?", [since]
            if args.get("direction"): sql += " AND direction=?"; params.append(args["direction"])
            if args.get("remote_ip"): sql += " AND remote_address=?"; params.append(args["remote_ip"])
            if args.get("kind"): sql += " AND kind=?"; params.append(args["kind"])
        elif name == "get_persistence_new":
            sql, params = "SELECT * FROM persistence_items WHERE first_seen>=?", [since]
        else:
            raise ValueError(f"Herramienta no permitida: {name}")
        return self._query(sql + " ORDER BY 1 DESC", params)

