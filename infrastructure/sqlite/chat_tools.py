# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Read-only tools for the chat model: compact, prioritized rows plus a summary a small model can reason over.

Every argument is validated against a closed list (case-insensitive, Spanish or English, several values allowed) and
every query is fixed SQL with bound parameters. Results carry at most ROW_LIMIT rows: a few hundred raw rows would
overflow a local model's context and push the instructions out of it.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from infrastructure.sqlite.connection import connect

ROW_LIMIT = 25
TEXT_LIMIT = 160
SEVERITY_ORDER = ("critical", "high", "medium", "low")
SEVERITY_ALIASES = {"critical": "critical", "critica": "critical", "crítica": "critical", "critico": "critical",
                    "crítico": "critical", "high": "high", "alta": "high", "alto": "high", "medium": "medium",
                    "media": "medium", "medio": "medium", "low": "low", "baja": "low", "bajo": "low"}
STATUS_ALIASES = {"open": ("new", "analyzed"), "abierta": ("new", "analyzed"), "abiertas": ("new", "analyzed"),
                  "new": ("new",), "nueva": ("new",), "nuevas": ("new",), "analyzed": ("analyzed",),
                  "analizada": ("analyzed",), "analizadas": ("analyzed",), "confirmed": ("confirmed",),
                  "confirmada": ("confirmed",), "confirmadas": ("confirmed",), "dismissed": ("dismissed",),
                  "descartada": ("dismissed",), "descartadas": ("dismissed",), "all": (), "todas": ()}
WINDOWS = {"1h": 1, "24h": 24, "7d": 168, "30d": 720, "today": 24, "hoy": 24, "week": 168, "semana": 168,
           "month": 720, "mes": 720}
DIRECTIONS = {"inbound": "inbound", "entrante": "inbound", "entrantes": "inbound", "outbound": "outbound",
              "saliente": "outbound", "salientes": "outbound", "listen": "listen", "escucha": "listen",
              "listening": "listen", "servidor": "listen"}


def _since(value: str | None) -> str:
    """'1h', '24h', '7d', '30d', 'hoy', 'semana'… or an ISO date; anything else is an error the model sees."""
    now = datetime.now(timezone.utc)
    if not value:
        return (now - timedelta(hours=24)).isoformat()
    text = str(value).strip().casefold()
    if text in WINDOWS:
        return (now - timedelta(hours=WINDOWS[text])).isoformat()
    match = re.fullmatch(r"(\d{1,4})\s*([hd])", text)
    if match:
        hours = int(match.group(1)) * (24 if match.group(2) == "d" else 1)
        return (now - timedelta(hours=min(hours, 24 * 365))).isoformat()
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()


def _choices(raw: Any, aliases: dict, label: str) -> list:
    """'CRITICAL,HIGH', ['alta', 'crítica'] or 'high' -> canonical values; unknown values are a clear error."""
    if raw in (None, "", []):
        return []
    items = raw if isinstance(raw, (list, tuple)) else re.split(r"[,;|/ ]+|\by\b|\band\b", str(raw))
    result = []
    for item in items:
        key = str(item).strip().casefold()
        if not key:
            continue
        if key not in aliases:
            raise ValueError(f"{label} no válido: {item!r}. Valores admitidos: {', '.join(sorted(set(aliases)))}")
        value = aliases[key]
        result.extend(value if isinstance(value, tuple) else [value])
    return list(dict.fromkeys(result))


def _like(text: str) -> str:
    return "%" + str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _short(value: Any) -> Any:
    return value[:TEXT_LIMIT] + "…" if isinstance(value, str) and len(value) > TEXT_LIMIT else value


class SQLiteQueryTools:
    def __init__(self, settings):
        self.settings = settings

    def _rows(self, db, sql: str, params: list, columns: tuple[str, ...]) -> list[dict]:
        return [{key: _short(row[key]) for key in columns if key in row.keys()}
                for row in db.execute(sql + f" LIMIT {ROW_LIMIT}", params)]

    def _summary(self, db, table: str, where: str, params: list, group: str | None, label: str) -> dict:
        total = int(db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])
        summary: dict[str, Any] = {"total": total, "returned": min(total, ROW_LIMIT)}
        if group:
            summary[label] = {str(row[0]): int(row[1]) for row in db.execute(
                f"SELECT {group}, COUNT(*) n FROM {table} WHERE {where} GROUP BY {group} ORDER BY n DESC LIMIT 8", params)}
        if total > ROW_LIMIT:
            summary["note"] = f"Se muestran {ROW_LIMIT} de {total}; use los filtros para acotar."
        return summary

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        args = dict(args or {})
        with connect(self.settings.database_path, readonly=True) as db:
            if name == "get_overview":
                return {"summary": self._overview(db, _since(args.get("since"))), "rows": []}
            # Open alerts stay relevant for weeks; everything else defaults to the last day
            since = _since(args.get("since") or ("30d" if name == "get_alerts" else None))
            if name == "get_alerts":
                severities = _choices(args.get("severity"), SEVERITY_ALIASES, "severity")
                statuses = _choices(args.get("status", "open"), STATUS_ALIASES, "status")
                where, params = "ts>=?", [since]
                if severities:
                    where += f" AND severity IN ({','.join('?' * len(severities))})"; params += severities
                if statuses:
                    where += f" AND status IN ({','.join('?' * len(statuses))})"; params += statuses
                if args.get("rule"):
                    where += " AND rule_id=?"; params.append(str(args["rule"]).upper())
                summary = self._summary(db, "alerts", where, params, "severity", "by_severity")
                summary["by_rule"] = {row[0]: {"count": int(row[1]), "title": row[2]} for row in db.execute(
                    f"SELECT rule_id, COUNT(*) n, MAX(title) FROM alerts WHERE {where} GROUP BY rule_id ORDER BY n DESC LIMIT 8",
                    params)}
                rank = "CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END"
                rows = self._rows(db, f"SELECT * FROM alerts WHERE {where} ORDER BY {rank} DESC, ts DESC", params,
                                  ("id", "ts", "severity", "rule_id", "title", "status", "evidence"))
                return {"summary": summary, "rows": rows}
            if name == "get_auth_events":
                where, params = "ts>=?", [since]
                if args.get("event_id") is not None:
                    where += " AND event_id=?"; params.append(int(args["event_id"]))
                if args.get("source_ip"):
                    where += " AND source_ip=?"; params.append(str(args["source_ip"]))
                if args.get("failed_only"):
                    where += " AND event_id=4625"
                return {"summary": self._summary(db, "auth_events", where, params, "event_id", "by_event_id"),
                        "rows": self._rows(db, f"SELECT * FROM auth_events WHERE {where} ORDER BY ts DESC", params,
                                           ("id", "ts", "event_id", "logon_type", "target_user", "source_ip", "source_host"))}
            if name == "get_connections":
                where, params = "ts>=?", [since]
                direction = _choices(args.get("direction"), DIRECTIONS, "direction")
                if direction:
                    where += f" AND direction IN ({','.join('?' * len(direction))})"; params += direction
                if args.get("process"):
                    where += " AND process_name LIKE ? ESCAPE '\\'"; params.append(_like(args["process"]))
                if args.get("remote_ip"):
                    where += " AND raddr=?"; params.append(str(args["remote_ip"]))
                if not args.get("include_local"):
                    where += " AND COALESCE(raddr, '') NOT LIKE '127.%' AND COALESCE(raddr, '') <> '::1'"
                # One row per distinct conversation, not one per snapshot
                rows = [dict(row) for row in db.execute(f"""
                    SELECT MAX(id) id, MAX(ts) last_seen, direction, process_name, laddr, lport, raddr, rport,
                           COUNT(*) observations FROM connections WHERE {where}
                    GROUP BY direction, process_name, lport, raddr, rport ORDER BY observations DESC LIMIT {ROW_LIMIT}""",
                    params)]
                return {"summary": self._summary(db, "connections", where, params, "process_name", "by_process"),
                        "rows": rows}
            if name == "get_processes":
                where, params = "s.ts>=?", [since]
                if args.get("process"):
                    where += " AND s.name LIKE ? ESCAPE '\\'"; params.append(_like(args["process"]))
                if args.get("active") is not None:
                    where += " AND l.active=?"; params.append(int(bool(args["active"])))
                latest = "s.run_id=(SELECT MAX(run_id) FROM process_snapshots)" if args.get("active", True) else "1=1"
                rows = [dict(row) for row in db.execute(f"""
                    SELECT s.id, s.ts, s.pid, s.name, s.path, s.parent_name, s.process_user,
                           ROUND(COALESCE(s.private_bytes, s.rss_bytes) / 1048576.0) memory_mb, s.memory_percent,
                           l.first_seen, l.active
                    FROM process_snapshots s JOIN process_lifecycle l ON l.process_key=s.process_key
                    WHERE {where} AND {latest} ORDER BY COALESCE(s.private_bytes, s.rss_bytes) DESC LIMIT {ROW_LIMIT}""",
                    params)]
                return {"summary": {"returned": len(rows), "ordered_by": "memoria privada (MB), de mayor a menor"},
                        "rows": [{key: _short(value) for key, value in row.items()} for row in rows]}
            if name == "get_file_events":
                where, params = "ts>=?", [since]
                if args.get("path_contains"):
                    where += " AND path LIKE ? ESCAPE '\\'"; params.append(_like(args["path_contains"]))
                if args.get("action"):
                    where += " AND action=?"; params.append(str(args["action"]))
                return {"summary": self._summary(db, "file_events", where, params, "action", "by_action"),
                        "rows": self._rows(db, f"SELECT * FROM file_events WHERE {where} ORDER BY ts DESC", params,
                                           ("id", "ts", "action", "path", "extension", "sha256", "process_name"))}
            if name == "get_file_reputation":
                where, params = "checked_at>=?", [since]
                if args.get("sha256"):
                    where += " AND sha256=?"; params.append(str(args["sha256"]).casefold())
                if args.get("path_contains"):
                    where += " AND path LIKE ? ESCAPE '\\'"; params.append(_like(args["path_contains"]))
                if args.get("verdict"):
                    where += " AND verdict=?"; params.append(str(args["verdict"]))
                return {"summary": self._summary(db, "file_reputation", where, params, "verdict", "by_verdict"),
                        "rows": self._rows(db, f"SELECT * FROM file_reputation WHERE {where} ORDER BY checked_at DESC",
                                           params, ("id", "checked_at", "path", "sha256", "verdict", "confidence",
                                                    "reasons_json"))}
            if name == "get_ssh_observations":
                where, params = "ts>=?", [since]
                for field, column in (("direction", "direction"), ("remote_ip", "remote_address"), ("kind", "kind")):
                    if args.get(field):
                        where += f" AND {column}=?"; params.append(str(args[field]))
                return {"summary": self._summary(db, "ssh_observations", where, params, "kind", "by_kind"),
                        "rows": self._rows(db, f"SELECT * FROM ssh_observations WHERE {where} ORDER BY ts DESC", params,
                                           ("id", "ts", "kind", "direction", "remote_address", "remote_port",
                                            "process_name", "tunnel_types", "agent_forwarding"))}
            if name == "get_persistence_new":
                where, params = "first_seen>=?", [since]
                return {"summary": self._summary(db, "persistence_items", where, params, "kind", "by_kind"),
                        "rows": self._rows(db, f"SELECT * FROM persistence_items WHERE {where} ORDER BY first_seen DESC",
                                           params, ("id", "first_seen", "kind", "name", "location", "command", "active"))}
        raise ValueError(f"Herramienta no permitida: {name}")

    def _overview(self, db, since: str) -> dict[str, Any]:
        """The whole picture in one call, for broad questions."""
        scalar = lambda sql, params=(): int(db.execute(sql, params).fetchone()[0] or 0)
        open_alerts = {row[0]: int(row[1]) for row in db.execute(
            "SELECT severity, COUNT(*) FROM alerts WHERE status IN ('new','analyzed') GROUP BY severity")}
        top_rules = {row[0]: {"count": int(row[1]), "title": row[2]} for row in db.execute(
            """SELECT rule_id, COUNT(*) n, MAX(title) FROM alerts WHERE status IN ('new','analyzed')
               GROUP BY rule_id ORDER BY n DESC LIMIT 5""")}
        last_collect = db.execute("SELECT MAX(COALESCE(finished_at, started_at)) FROM runs WHERE kind='collect'").fetchone()[0]
        return {
            "window_start": since, "last_collection": last_collect,
            "open_alerts_by_severity": open_alerts, "open_alerts_top_rules": top_rules,
            "new_alerts_in_window": scalar("SELECT COUNT(*) FROM alerts WHERE ts>=?", (since,)),
            "remote_ips": scalar("""SELECT COUNT(DISTINCT raddr) FROM connections WHERE ts>=? AND raddr IS NOT NULL
                                    AND raddr NOT LIKE '127.%' AND raddr <> '::1'""", (since,)),
            "listening_ports": scalar("SELECT COUNT(DISTINCT lport) FROM connections WHERE ts>=? AND direction='listen'", (since,)),
            "failed_logons": scalar("SELECT COUNT(*) FROM auth_events WHERE ts>=? AND event_id=4625", (since,)),
            "remote_logons": scalar("""SELECT COUNT(*) FROM auth_events WHERE ts>=?
                                       AND (event_id=1149 OR (event_id=4624 AND logon_type=10))""", (since,)),
            "file_events": scalar("SELECT COUNT(*) FROM file_events WHERE ts>=?", (since,)),
            "new_persistence": scalar("SELECT COUNT(*) FROM persistence_items WHERE first_seen>=?", (since,)),
            "firewall_blocks": scalar("SELECT COUNT(*) FROM firewall_events WHERE ts>=? AND action='DROP'", (since,)),
            "active_processes": scalar("SELECT COUNT(*) FROM process_lifecycle WHERE active=1"),
        }
