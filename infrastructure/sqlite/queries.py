from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from infrastructure.sqlite.connection import connect
from settings import Settings


ALLOWED_TABLES = {"connections", "auth_events", "file_events", "file_reputation", "firewall_events", "persistence_items", "alerts", "llm_analyses", "runs", "ssh_observations", "process_snapshots", "process_lifecycle"}

ROWS_LIMIT = 5000  # most recent rows per table and window that the GUI loads
ENTITY_LIMIT = 200
# Live timeline: one fixed SELECT per event type, each naming its columns (a UNION takes the names of
# whichever SELECT comes first) and binding `since`
LIVE_SOURCES = {
    "alerta": "SELECT ts, 'alerta' tipo, severity nivel, title resumen, rule_id origen, id entidad_id FROM alerts WHERE ts>=?",
    "conexión": """SELECT ts, 'conexión' tipo, CASE WHEN direction='inbound' THEN 'medium' ELSE 'info' END nivel,
        COALESCE(process_name,'?') || ' → ' || COALESCE(raddr,laddr,'?') || ':' || COALESCE(rport,lport,'?') resumen,
        COALESCE(direction,source) origen, id entidad_id FROM connections WHERE ts>=? AND state NOT IN ('TIME_WAIT','CLOSE_WAIT')""",
    "acceso": """SELECT ts, 'acceso' tipo, CASE WHEN event_id IN (4625,4771,1102) THEN 'medium' ELSE 'info' END nivel,
        COALESCE(target_user,'?') || ' desde ' || COALESCE(source_ip,source_host,'local') resumen,
        CAST(event_id AS TEXT) origen, id entidad_id FROM auth_events WHERE ts>=?""",
    "archivo": "SELECT ts, 'archivo' tipo, 'info' nivel, path resumen, action origen, id entidad_id FROM file_events WHERE ts>=?",
    "firewall": """SELECT ts, 'firewall' tipo, CASE WHEN lower(action) IN ('drop','block') THEN 'medium' ELSE 'info' END nivel,
        COALESCE(src_ip,'?') || ' → ' || COALESCE(dst_ip,'?') || ':' || COALESCE(dst_port,'?') resumen,
        COALESCE(action,'?') origen, id entidad_id FROM firewall_events WHERE ts>=?""",
    "ssh": """SELECT ts, 'ssh' tipo, CASE WHEN direction='inbound' THEN 'medium' ELSE 'info' END nivel,
        COALESCE(process_name,'ssh') || ' → ' || COALESCE(remote_address,'local') resumen, kind origen, id entidad_id
        FROM ssh_observations WHERE ts>=?""",
}
LIVE_TABLES = {"alerta": "alerts", "conexión": "connections", "acceso": "auth_events", "archivo": "file_events",
               "firewall": "firewall_events", "ssh": "ssh_observations"}
# table -> (window column or None for inventories, searchable columns); names are code, never user input
ENTITY_SOURCES = {
    "alerts": ("ts", ("title", "evidence")),
    "connections": ("ts", ("raddr", "laddr", "process_name", "process_path", "process_user")),
    "firewall_events": ("ts", ("src_ip", "dst_ip", "dst_port")),
    "auth_events": ("ts", ("source_ip", "source_host", "target_user", "process_name")),
    "file_events": ("ts", ("path", "dest_path", "sha256", "process_name")),
    "ssh_observations": ("ts", ("remote_address", "local_address", "process_name", "process_user", "command_summary")),
    "process_lifecycle": (None, ("name", "path", "process_user")),
    "persistence_items": (None, ("name", "location", "command")),
    "file_reputation": (None, ("sha256", "path")),
}


class SQLiteQueryRepository:
    def __init__(self, settings: Settings):
        self.settings = settings

    def rows(self, table: str, since: str | None = None, limit: int = ROWS_LIMIT):
        if table not in ALLOWED_TABLES:
            raise ValueError("Tabla no permitida")
        column = ("first_seen" if table in {"persistence_items", "process_lifecycle"} else "started_at" if table == "runs"
                  else "checked_at" if table == "file_reputation" else "ts")
        sql = f"SELECT * FROM {table}"
        params = []
        if since:
            sql += f" WHERE {column}>=?"
            params.append(since)
        sql += f" ORDER BY {column} DESC LIMIT ?"
        params.append(min(max(int(limit), 1), ROWS_LIMIT))
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

    def connections(self, since: str, latest_only: bool = False, limit: int = 20000):
        """Connection rows in the window; with latest_only, just the most recent psutil snapshot."""
        with connect(self.settings.database_path, readonly=True) as db:
            if latest_only:
                run = db.execute("SELECT MAX(run_id) FROM connections WHERE source='psutil' AND ts>=?", (since,)).fetchone()[0]
                if run is None:
                    return []
                sql, params = "SELECT * FROM connections WHERE run_id=? LIMIT ?", (run, limit)
            else:
                sql, params = "SELECT * FROM connections WHERE ts>=? ORDER BY ts LIMIT ?", (since, limit)
            return [dict(row) for row in db.execute(sql, params)]

    def processes_current(self, limit: int = 2000):
        with connect(self.settings.database_path, readonly=True) as db:
            run = db.execute("SELECT MAX(run_id) FROM process_snapshots").fetchone()[0]
            if run is None: return []
            return [dict(row) for row in db.execute(
                "SELECT * FROM process_snapshots WHERE run_id=? ORDER BY COALESCE(private_bytes,rss_bytes) DESC LIMIT ?",
                (run, min(max(limit, 1), 5000)))]

    def process_history(self, since: str, process_key: str | None = None, limit: int = 20000):
        sql, params = "SELECT * FROM process_snapshots WHERE ts>=?", [since]
        if process_key:
            sql += " AND process_key=?"; params.append(process_key)
        sql += " ORDER BY ts LIMIT ?"; params.append(min(max(limit, 1), 20000))
        with connect(self.settings.database_path, readonly=True) as db:
            return [dict(row) for row in db.execute(sql, tuple(params))]

    def process_lifecycle(self, active: bool | None = None, limit: int = 2000):
        sql, params = "SELECT * FROM process_lifecycle", []
        if active is not None:
            sql += " WHERE active=?"; params.append(int(active))
        sql += " ORDER BY last_seen DESC LIMIT ?"; params.append(min(max(limit, 1), 5000))
        with connect(self.settings.database_path, readonly=True) as db:
            return [dict(row) for row in db.execute(sql, tuple(params))]

    def open_alerts_by_severity(self) -> dict[str, int]:
        with connect(self.settings.database_path, readonly=True) as db:
            rows = db.execute("SELECT severity, COUNT(*) FROM alerts WHERE status IN ('new','analyzed') GROUP BY severity")
            return {row[0]: int(row[1]) for row in rows}

    def live_status(self) -> dict:
        """Small current-state snapshot for the operations screen; never loads historical tables."""
        with connect(self.settings.database_path, readonly=True) as db:
            alert_rows = db.execute(
                "SELECT severity, COUNT(*) FROM alerts WHERE status IN ('new','analyzed') GROUP BY severity"
            ).fetchall()
            process_run = db.execute("SELECT MAX(run_id) FROM process_snapshots").fetchone()[0]
            if process_run is None:
                process_count = memory_bytes = 0
                process_ts = None
            else:
                process_count, memory_bytes, process_ts = db.execute(
                    "SELECT COUNT(*), COALESCE(SUM(COALESCE(private_bytes,rss_bytes)),0), MAX(ts) "
                    "FROM process_snapshots WHERE run_id=?", (process_run,),
                ).fetchone()
            connection_run = db.execute(
                "SELECT MAX(run_id) FROM connections WHERE source='psutil'"
            ).fetchone()[0]
            if connection_run is None:
                connections = listeners = 0
                connection_ts = None
            else:
                connections, listeners, connection_ts = db.execute(
                    "SELECT SUM(CASE WHEN state NOT IN ('LISTEN','TIME_WAIT','CLOSE_WAIT') THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN state='LISTEN' THEN 1 ELSE 0 END), MAX(ts) FROM connections WHERE run_id=?",
                    (connection_run,),
                ).fetchone()
            last_run = db.execute(
                "SELECT id,kind,started_at,finished_at,status,heartbeat_at FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return {
            "alerts": {row[0]: int(row[1]) for row in alert_rows},
            "processes": int(process_count or 0), "memory_bytes": int(memory_bytes or 0),
            "connections": int(connections or 0), "listeners": int(listeners or 0),
            "process_ts": process_ts, "connection_ts": connection_ts,
            "last_run": dict(last_run) if last_run else None,
        }

    def live_freshness(self) -> list[dict]:
        """Latest timestamp per evidence source, using indexed MAX queries."""
        sources = (
            ("Procesos", "process_snapshots", "ts"), ("Conexiones", "connections", "ts"),
            ("Accesos", "auth_events", "ts"), ("Archivos", "file_events", "ts"),
            ("Firewall", "firewall_events", "ts"), ("SSH", "ssh_observations", "ts"),
            ("Alertas", "alerts", "ts"),
        )
        with connect(self.settings.database_path, readonly=True) as db:
            return [{"fuente": label, "ultima_observacion": db.execute(
                f"SELECT MAX({column}) FROM {table}").fetchone()[0]} for label, table, column in sources]

    def live_runs(self, limit: int = 10) -> list[dict]:
        """Recent jobs and their per-collector outcome for operational diagnostics."""
        limit = min(max(int(limit), 1), 50)
        with connect(self.settings.database_path, readonly=True) as db:
            rows = db.execute(
                "SELECT id,kind,started_at,finished_at,status,heartbeat_at,is_admin,collectors "
                "FROM runs ORDER BY id DESC LIMIT ?", (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["collectors"] = json.loads(item["collectors"]) if item["collectors"] else {}
            except (TypeError, json.JSONDecodeError):
                item["collectors"] = {"manifiesto": {"status": "error", "warnings": ["JSON inválido"]}}
            result.append(item)
        return result

    def live_events(self, since: str, limit: int = 200, types=None, text: str | None = None,
                    relevant_only: bool = False) -> list[dict]:
        """Recent heterogeneous evidence as a bounded timeline; values remain data, never executable markup.

        Type, level and text filters run in SQL, so a busy source (file scans) cannot hide the others.
        """
        limit = min(max(int(limit), 1), 500)
        selected = [name for name in LIVE_SOURCES if types is None or name in set(types)]
        if not selected:
            return []
        sql = "SELECT * FROM (" + " UNION ALL ".join(LIVE_SOURCES[name] for name in selected) + ") WHERE 1=1"
        params: list = [since] * len(selected)
        if relevant_only:
            sql += " AND nivel <> 'info'"
        needle = " ".join(str(text or "").split())[:200]
        if needle:
            sql += " AND (resumen LIKE ? ESCAPE '\\' OR origen LIKE ? ESCAPE '\\')"
            pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params += [pattern, pattern]
        sql += " ORDER BY ts DESC LIMIT ?"
        with connect(self.settings.database_path, readonly=True) as db:
            return [dict(row) for row in db.execute(sql, (*params, limit))]

    def live_activity(self, since: str) -> list[dict]:
        """Events per minute and type since `since` (UTC minute buckets) for the pulse chart."""
        sql = " UNION ALL ".join(
            f"SELECT substr(ts,1,16) minuto, '{name}' tipo, COUNT(*) total FROM {table} WHERE ts>=? GROUP BY minuto"
            for name, table in LIVE_TABLES.items())
        with connect(self.settings.database_path, readonly=True) as db:
            return [dict(row) for row in db.execute(sql, [since] * len(LIVE_TABLES))]

    def open_alerts(self, limit: int = 8):
        with connect(self.settings.database_path, readonly=True) as db:
            return [dict(row) for row in db.execute(
                """SELECT id, ts, rule_id, severity, title FROM alerts WHERE status IN ('new','analyzed')
                ORDER BY CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC, ts DESC
                LIMIT ?""", (limit,))]

    def last_run(self, kind: str):
        with connect(self.settings.database_path, readonly=True) as db:
            row = db.execute("SELECT * FROM runs WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,)).fetchone()
        return dict(row) if row else None

    def grouped(self, table: str, column: str, since: str, limit: int = 15):
        """Top values of one column in the window (column names come from code, never from the user)."""
        allowed = {("auth_events", "event_id"), ("auth_events", "source_ip"), ("auth_events", "target_user"),
                   ("file_events", "action"), ("file_events", "extension"), ("persistence_items", "kind"),
                   ("firewall_events", "src_ip"), ("firewall_events", "dst_port"), ("firewall_events", "action")}
        if (table, column) not in allowed:
            raise ValueError("Agrupación no permitida")
        ts = "first_seen" if table == "persistence_items" else "ts"
        with connect(self.settings.database_path, readonly=True) as db:
            rows = db.execute(f"SELECT {column}, COUNT(*) FROM {table} WHERE {ts}>=? AND {column} IS NOT NULL "
                              f"GROUP BY {column} ORDER BY 2 DESC LIMIT ?", (since, limit))
            return [{"valor": row[0], "total": int(row[1])} for row in rows]

    def hourly(self, table: str, since: str, by: str | None = None):
        """Events per hour, optionally split by one column (same allow-list as `grouped`)."""
        if table not in {"auth_events", "file_events", "firewall_events", "connections", "alerts"}:
            raise ValueError("Tabla no permitida")
        if by and by not in {"event_id", "action", "direction", "severity"}:
            raise ValueError("Columna no permitida")
        split = f", {by}" if by else ""
        with connect(self.settings.database_path, readonly=True) as db:
            rows = db.execute(f"SELECT substr(ts,1,13) || ':00:00+00:00' hora{split}, COUNT(*) FROM {table} "
                              f"WHERE ts>=? GROUP BY hora{split} ORDER BY hora", (since,))
            return [{"hora": row[0], **({"serie": str(row[1])} if by else {}), "total": int(row[-1])} for row in rows]

    def latest_analysis(self):
        with connect(self.settings.database_path, readonly=True) as db:
            row = db.execute("SELECT * FROM llm_analyses ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        result = dict(row)
        result["result_json"] = json.loads(result["result_json"]) if result["result_json"] else None
        return result

    def llm_incidents_for(self, alert_id: int, analyses: int = 20):
        """Incidents from recent LLM analyses that cite this alert."""
        with connect(self.settings.database_path, readonly=True) as db:
            rows = db.execute("SELECT model, result_json FROM llm_analyses WHERE result_json IS NOT NULL ORDER BY id DESC LIMIT ?", (analyses,)).fetchall()
        found = []
        for model, result_json in rows:
            for incident in json.loads(result_json).get("incidents", []):
                if alert_id in incident.get("alert_ids", []):
                    found.append({**incident, "model": model})
        return found

    def alert_evidence(self, alert_id: int):
        with connect(self.settings.database_path, readonly=True) as db:
            rows = db.execute("SELECT entity_type, entity_id, snapshot_json FROM alert_evidence WHERE alert_id=? LIMIT 500", (alert_id,))
            return [{"entity_type": row[0], "entity_id": row[1], **json.loads(row[2])} for row in rows]


    def latest_section_summary(self, section: str) -> dict:
        """{'ok': latest successful summary or None, 'last': latest attempt or None} for one GUI section."""
        from infrastructure.sqlite.section_summaries import SQLiteSectionSummaryStore
        store = SQLiteSectionSummaryStore(self.settings)
        return {"ok": store.latest(section, successful_only=True), "last": store.latest(section)}

    def alert(self, alert_id: int):
        with connect(self.settings.database_path, readonly=True) as db:
            row = db.execute("SELECT * FROM alerts WHERE id=?", (int(alert_id),)).fetchone()
            return dict(row) if row else None

    def entity_search(self, term: str, since: str, limit: int = ENTITY_LIMIT) -> dict[str, list[dict]]:
        """Every table that mentions an IP, process, path, hash or user (substring, case-insensitive).

        Column names are fixed here; the term only travels as a bound LIKE pattern with its wildcards escaped.
        Inventories (reputation, persistence, process lifecycle) are searched regardless of the window.
        """
        needle = " ".join(str(term).replace("\x00", " ").split())[:200]
        if len(needle) < 2:
            raise ValueError("Escriba al menos 2 caracteres")
        pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        limit = min(max(int(limit), 1), ENTITY_LIMIT)
        results = {}
        with connect(self.settings.database_path, readonly=True) as db:
            for name, (time_column, columns) in ENTITY_SOURCES.items():
                where = " OR ".join(f"CAST({column} AS TEXT) LIKE ? ESCAPE '\\'" for column in columns)
                sql, params = f"SELECT * FROM {name} WHERE ({where})", [pattern] * len(columns)
                if time_column:
                    sql += f" AND {time_column}>=?"; params.append(since)
                sql += f" ORDER BY {time_column or 'rowid'} DESC LIMIT ?"; params.append(limit)
                results[name] = [{key: value for key, value in dict(row).items() if key != "raw_xml"}
                                 for row in db.execute(sql, params)]
        return results

def since_hours(hours: int) -> str:
    """Start of the window, rounded down to the minute so repeated reads within a minute share a cache key."""
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    return (now - timedelta(hours=hours)).isoformat()
