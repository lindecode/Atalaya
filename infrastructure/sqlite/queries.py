from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from infrastructure.sqlite.connection import connect
from settings import Settings


ALLOWED_TABLES = {"connections", "auth_events", "file_events", "firewall_events", "persistence_items", "alerts", "llm_analyses", "runs"}


class SQLiteQueryRepository:
    def __init__(self, settings: Settings):
        self.settings = settings

    def rows(self, table: str, since: str | None = None, limit: int = 5000):
        if table not in ALLOWED_TABLES:
            raise ValueError("Tabla no permitida")
        column = "first_seen" if table == "persistence_items" else "started_at" if table == "runs" else "ts"
        sql = f"SELECT * FROM {table}"
        params = []
        if since:
            sql += f" WHERE {column}>=?"
            params.append(since)
        sql += f" ORDER BY {column} DESC LIMIT ?"
        params.append(min(max(int(limit), 1), 5000))
        with connect(self.settings.database_path, readonly=True) as db:
            return [dict(row) for row in db.execute(sql, tuple(params))]

    def counts(self, since: str):
        result = {}
        with connect(self.settings.database_path, readonly=True) as db:
            for table, column in (("alerts", "ts"), ("auth_events", "ts"), ("connections", "ts"),
                                  ("file_events", "ts"), ("persistence_items", "first_seen")):
                result[table] = int(db.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}>=?", (since,)).fetchone()[0])
        return result

    def timeline(self, since: str):
        parts = []
        with connect(self.settings.database_path, readonly=True) as db:
            for table, label in (("auth_events", "accesos"), ("connections", "conexiones"), ("file_events", "archivos"), ("alerts", "alertas")):
                rows = db.execute(
                    f"SELECT substr(ts,1,13) || ':00:00' bucket, COUNT(*) count FROM {table} WHERE ts>=? GROUP BY bucket ORDER BY bucket",
                    (since,),
                )
                parts.extend({"bucket": row[0], "count": row[1], "type": label} for row in rows)
        return parts

    def latest_analysis(self):
        with connect(self.settings.database_path, readonly=True) as db:
            row = db.execute("SELECT * FROM llm_analyses ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        result = dict(row)
        result["result_json"] = json.loads(result["result_json"]) if result["result_json"] else None
        return result

    def alert_evidence(self, alert_id: int):
        with connect(self.settings.database_path, readonly=True) as db:
            rows = db.execute("SELECT entity_type, entity_id, snapshot_json FROM alert_evidence WHERE alert_id=? LIMIT 500", (alert_id,))
            return [{"entity_type": row[0], "entity_id": row[1], **json.loads(row[2])} for row in rows]


def since_hours(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
