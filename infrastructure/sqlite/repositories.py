from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from domain.models import AlertCandidate, CollectionResult, EvidenceView
from domain.rules.base import INVALID_IPS, baseline_key
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.migrations import MIGRATIONS
from settings import Settings


TABLES = (
    "runs", "connections", "auth_events", "file_events", "firewall_events",
    "persistence_items", "baseline", "alerts", "llm_analyses", "cursors", "sysmon_events", "preferences",
)
BASELINE_RULES = ("R03", "R04", "R05", "R10")


class SQLiteRepository:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def database_path(self) -> Path:
        return self.settings.database_path

    def _connect(self, readonly: bool = False) -> sqlite3.Connection:
        return connect(
            self.database_path,
            self.settings.sqlite_busy_timeout_ms,
            readonly=readonly,
        )

    def initialize(self) -> None:
        self.settings.ensure_runtime_dirs()
        with self._connect() as db:
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if version > len(MIGRATIONS):
                raise RuntimeError(f"La BD usa una versión futura no compatible: {version}")
            for index, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                db.executescript(sql)
                db.execute(f"PRAGMA user_version={index}")

    def start_run(self, kind: str, started_at: str, is_admin: bool) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO runs(kind, started_at, is_admin, status, heartbeat_at) VALUES (?, ?, ?, 'running', ?)",
                (kind, started_at, int(is_admin), started_at),
            )
            return int(cursor.lastrowid)

    def get_cursor(self, source: str) -> dict[str, Any] | None:
        with self._connect(readonly=True) as db:
            row = db.execute("SELECT value_json FROM cursors WHERE source=?", (source,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _connection_key(run_id: int, values: dict[str, Any]) -> str:
        fields = (run_id, values["source"], values["proto"], values["laddr"], values["lport"],
                  values["raddr"], values["rport"], values["pid"], values["state"])
        return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode("utf-8")).hexdigest()

    def save_collection(self, run_id: int, result: CollectionResult, now: str) -> int:
        inserted = 0
        with self._connect() as db:
            if result.item_kind == "connections":
                for item in result.items:
                    values = asdict(item)
                    key = self._connection_key(run_id, values)
                    cursor = db.execute(
                        """INSERT OR IGNORE INTO connections
                        (run_id, ts, source, proto, direction, laddr, lport, raddr, rport, state,
                         pid, process_name, process_path, process_user, signed, dedup_key)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (run_id, values["ts"], values["source"], values["proto"], values["direction"],
                         values["laddr"], values["lport"], values["raddr"], values["rport"], values["state"],
                         values["pid"], values["process_name"], values["process_path"], values["process_user"],
                         None if values["signed"] is None else int(values["signed"]), key),
                    )
                    inserted += max(cursor.rowcount, 0)
            elif result.item_kind == "auth_events":
                for item in result.items:
                    v = asdict(item)
                    cursor = db.execute(
                        """INSERT OR IGNORE INTO auth_events
                        (ts, channel, event_id, record_id, logon_type, target_user, source_ip,
                         source_host, process_name, status_code, raw_xml)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        tuple(v[key] for key in ("ts", "channel", "event_id", "record_id", "logon_type",
                              "target_user", "source_ip", "source_host", "process_name", "status_code", "raw_xml")),
                    )
                    inserted += max(cursor.rowcount, 0)
            elif result.item_kind == "file_events":
                for item in result.items:
                    v = asdict(item)
                    cursor = db.execute(
                        """INSERT OR IGNORE INTO file_events
                        (ts, source, action, path, dest_path, extension, size, sha256, process_name, dedup_key)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        tuple(v[key] for key in ("ts", "source", "action", "path", "dest_path", "extension",
                                                "size", "sha256", "process_name", "dedup_key")),
                    )
                    inserted += max(cursor.rowcount, 0)
            elif result.item_kind == "firewall_events":
                for item in result.items:
                    v = asdict(item)
                    cursor = db.execute(
                        """INSERT OR IGNORE INTO firewall_events
                        (ts, action, proto, src_ip, src_port, dst_ip, dst_port, direction, dedup_key)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        tuple(v[key] for key in ("ts", "action", "proto", "src_ip", "src_port", "dst_ip", "dst_port", "direction", "dedup_key")),
                    )
                    inserted += max(cursor.rowcount, 0)
            elif result.item_kind == "sysmon_events":
                for item in result.items:
                    v = asdict(item)
                    cursor = db.execute(
                        """INSERT OR IGNORE INTO sysmon_events(ts, event_id, record_id, process_name, data_json)
                        VALUES (?, ?, ?, ?, ?)""",
                        (v["ts"], v["event_id"], v["record_id"], v["process_name"], json.dumps(v["data"], ensure_ascii=False)),
                    )
                    inserted += max(cursor.rowcount, 0)
            elif result.item_kind == "persistence_items":
                db.execute("UPDATE persistence_items SET active=0, last_missing_at=? WHERE active=1", (now,))
                for item in result.items:
                    v = asdict(item)
                    identity = (v["kind"], v["location"], v["name"] or "")
                    existed = db.execute(
                        "SELECT 1 FROM persistence_items WHERE kind=? AND location=? AND name=?", identity
                    ).fetchone() is not None
                    db.execute(
                        """INSERT INTO persistence_items
                        (first_seen, last_seen, kind, location, name, command, active, last_missing_at)
                        VALUES (?, ?, ?, ?, ?, ?, 1, NULL)
                        ON CONFLICT(kind, location, name) DO UPDATE SET
                          last_seen=excluded.last_seen, command=excluded.command, active=1, last_missing_at=NULL""",
                        (v["first_seen"], v["last_seen"], v["kind"], v["location"], v["name"] or "", v["command"]),
                    )
                    inserted += int(not existed)
            else:
                raise ValueError(f"Tipo de colección desconocido: {result.item_kind}")

            if result.next_cursor is not None:
                db.execute(
                    """INSERT INTO cursors(source, value_json, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(source) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at""",
                    (result.collector, json.dumps(result.next_cursor, ensure_ascii=False), now),
                )
            db.execute("UPDATE runs SET heartbeat_at=? WHERE id=?", (now, run_id))
        return inserted

    def finish_run(self, run_id: int, finished_at: str, status: str, collectors: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE runs SET finished_at=?, heartbeat_at=?, status=?, collectors=? WHERE id=?",
                (finished_at, finished_at, status, json.dumps(collectors, ensure_ascii=False), run_id),
            )

    def status(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "database": str(self.database_path),
            "database_bytes": self.database_path.stat().st_size if self.database_path.exists() else 0,
            "tables": {},
            "last_run": None,
        }
        with self._connect(readonly=True) as db:
            for table in TABLES:
                result["tables"][table] = int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            row = db.execute(
                "SELECT id, kind, started_at, finished_at, is_admin, status, collectors FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                result["last_run"] = dict(row)
                if row["collectors"]:
                    result["last_run"]["collectors"] = json.loads(row["collectors"])
        return result

    @staticmethod
    def _rows(db: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> tuple[dict[str, Any], ...]:
        return tuple(dict(row) for row in db.execute(sql, params).fetchall())

    def load_evidence(self, since: str) -> EvidenceView:
        with self._connect(readonly=True) as db:
            baseline = frozenset(
                (str(row["kind"]), str(row["value"]))
                for row in db.execute("SELECT kind, value FROM baseline WHERE approved=1")
            )
            return EvidenceView(
                auth_events=self._rows(db, "SELECT * FROM auth_events WHERE ts>=? ORDER BY ts", (since,)),
                connections=self._rows(db, "SELECT * FROM connections WHERE ts>=? ORDER BY ts", (since,)),
                file_events=self._rows(db, "SELECT * FROM file_events WHERE ts>=? ORDER BY ts", (since,)),
                firewall_events=self._rows(db, "SELECT * FROM firewall_events WHERE ts>=? ORDER BY ts", (since,)),
                persistence_items=self._rows(db, "SELECT * FROM persistence_items WHERE first_seen>=? ORDER BY first_seen", (since,)),
                baseline=baseline,
            )

    def save_alerts(self, candidates: list[AlertCandidate]) -> list[int]:
        inserted_ids: list[int] = []
        with self._connect() as db:
            for alert in candidates:
                dedup = hashlib.sha256(f"{alert.rule_id}|{alert.entity}|{alert.window_key}".encode("utf-8")).hexdigest()
                cursor = db.execute(
                    """INSERT OR IGNORE INTO alerts(ts, rule_id, severity, title, evidence, dedup_key)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (alert.ts, alert.rule_id, alert.severity, alert.title, json.dumps(alert.summary, ensure_ascii=False), dedup),
                )
                if cursor.rowcount <= 0:
                    continue
                alert_id = int(cursor.lastrowid)
                inserted_ids.append(alert_id)
                for evidence in alert.evidence:
                    db.execute(
                        """INSERT INTO alert_evidence(alert_id, entity_type, entity_id, snapshot_json)
                        VALUES (?, ?, ?, ?)""",
                        (alert_id, evidence.entity_type, evidence.entity_id, json.dumps(evidence.snapshot, ensure_ascii=False)),
                    )
        return inserted_ids

    def get_new_alerts(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect(readonly=True) as db:
            alerts = [dict(row) for row in db.execute(
                "SELECT * FROM alerts WHERE status='new' ORDER BY CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC, ts LIMIT ?",
                (limit,),
            )]
            for alert in alerts:
                alert["evidence"] = json.loads(alert["evidence"])
                alert["examples"] = [json.loads(row[0]) for row in db.execute(
                    "SELECT snapshot_json FROM alert_evidence WHERE alert_id=? LIMIT 10", (alert["id"],)
                )]
        return alerts

    def save_llm_analysis(self, run_id: int, ts: str, model: str, alert_ids: list[int], prompt_chars: int,
                          result: dict[str, Any] | None, error: str | None, duration_ms: int) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO llm_analyses(run_id, ts, model, alert_ids, prompt_chars, result_json, error, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, ts, model, json.dumps(alert_ids), prompt_chars,
                 json.dumps(result, ensure_ascii=False) if result else None, error, duration_ms),
            )
            if result:
                db.executemany("UPDATE alerts SET status='analyzed', status_at=? WHERE id=? AND status='new'", ((ts, alert_id) for alert_id in alert_ids))

    def update_alert_status(self, alert_id: int, status: str, note: str | None, ts: str) -> None:
        if status not in {"new", "analyzed", "dismissed", "confirmed"}:
            raise ValueError("Estado de alerta inválido")
        with self._connect() as db:
            cursor = db.execute("UPDATE alerts SET status=?, status_note=?, status_at=? WHERE id=?", (status, note, ts, alert_id))
            if cursor.rowcount != 1:
                raise KeyError(f"Alerta inexistente: {alert_id}")

    def approve_baseline(self, kind: str, value: str, ts: str) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO baseline(kind, value, first_seen, last_seen, times_seen, approved)
                VALUES (?, ?, ?, ?, 1, 1)
                ON CONFLICT(kind, value) DO UPDATE SET last_seen=excluded.last_seen, approved=1""",
                (kind, value, ts, ts),
            )

    def count_runs(self, kind: str) -> int:
        with self._connect(readonly=True) as db:
            return int(db.execute("SELECT COUNT(*) FROM runs WHERE kind=?", (kind,)).fetchone()[0])

    def get_preference(self, key: str) -> str | None:
        with self._connect(readonly=True) as db:
            row = db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_preference(self, key: str, value: str, ts: str) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO preferences(key, value, updated_at) VALUES (?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""", (key, value, ts))

    def approve_all_observed(self, ts: str) -> dict[str, int]:
        """Treat everything seen so far as normal: listen ports, logon sources and every active persistence item."""
        with self._connect() as db:
            observed = {(row[0], row[1]) for row in db.execute("SELECT kind, value FROM baseline WHERE approved=0")}
            for row in db.execute("SELECT DISTINCT process_name, lport FROM connections WHERE direction='listen'"):
                observed.add(baseline_key("R05", dict(row)))
            for row in db.execute("SELECT DISTINCT source_ip FROM auth_events WHERE event_id=4624"):
                observed.add(baseline_key("R03", dict(row)))
            for row in db.execute("SELECT kind, location, name FROM persistence_items WHERE active=1"):
                observed.add(baseline_key("R10", dict(row)))
            observed.discard(None)
            counts: dict[str, int] = {}
            for kind, value in observed:
                db.execute(
                    """INSERT INTO baseline(kind, value, first_seen, last_seen, times_seen, approved)
                    VALUES (?, ?, ?, ?, 1, 1)
                    ON CONFLICT(kind, value) DO UPDATE SET last_seen=excluded.last_seen, approved=1""",
                    (kind, value, ts, ts),
                )
                counts[kind] = counts.get(kind, 0) + 1
        return counts

    @staticmethod
    def _alert_baseline_key(db: sqlite3.Connection, alert_id: int, rule_id: str) -> tuple[str, str] | None:
        row = db.execute("SELECT snapshot_json FROM alert_evidence WHERE alert_id=? LIMIT 1", (alert_id,)).fetchone()
        return baseline_key(rule_id, json.loads(row[0])) if row else None

    def dismiss_baselined(self, note: str, ts: str) -> int:
        """Dismiss open alerts whose entity is now in the approved baseline."""
        placeholders = ",".join("?" * len(BASELINE_RULES))
        with self._connect() as db:
            approved = {(row[0], row[1]) for row in db.execute("SELECT kind, value FROM baseline WHERE approved=1")}
            open_alerts = db.execute(
                f"SELECT id, rule_id FROM alerts WHERE status IN ('new','analyzed') AND rule_id IN ({placeholders})",
                BASELINE_RULES,
            ).fetchall()
            covered = [row[0] for row in open_alerts if self._alert_baseline_key(db, row[0], row[1]) in approved]
            db.executemany("UPDATE alerts SET status='dismissed', status_note=?, status_at=? WHERE id=?",
                           ((note, ts, alert_id) for alert_id in covered))
        return len(covered)

    def approve_alert(self, alert_id: int, ts: str) -> tuple[str, str]:
        """Add the alert's entity to the baseline, then dismiss every open alert it covers."""
        with self._connect(readonly=True) as db:
            row = db.execute("SELECT rule_id FROM alerts WHERE id=?", (alert_id,)).fetchone()
            if not row:
                raise KeyError(f"Alerta inexistente: {alert_id}")
            key = self._alert_baseline_key(db, alert_id, row[0])
        if key is None:
            raise ValueError(f"La regla {row[0]} no admite baseline; use confirmar o descartar")
        self.approve_baseline(*key, ts)
        self.dismiss_baselined("Aprobado como normal", ts)
        return key

    def observe_baseline(self, view: EvidenceView, ts: str, approve: bool = False) -> None:
        observations: set[tuple[str, str]] = set()
        for row in view.connections:
            process = str(row.get("process_name") or "")
            if process:
                observations.add(("process_net", process))
            if row.get("direction") == "listen":
                observations.add(("listen_port", f"{process or '?'}|{row.get('lport')}"))
            if row.get("raddr"):
                observations.add(("remote_ip", str(row["raddr"])))
        for row in view.auth_events:
            if row.get("event_id") == 4624 and str(row.get("source_ip") or "") not in INVALID_IPS:
                observations.add(("logon_source", str(row["source_ip"])))
        for row in view.persistence_items:
            if row.get("active"):
                observations.add(baseline_key("R10", row))
        observations.discard(None)
        with self._connect() as db:
            for kind, value in observations:
                db.execute(
                    """INSERT INTO baseline(kind, value, first_seen, last_seen, times_seen, approved)
                    VALUES (?, ?, ?, ?, 1, ?)
                    ON CONFLICT(kind, value) DO UPDATE SET last_seen=excluded.last_seen,
                      times_seen=baseline.times_seen+1, approved=MAX(baseline.approved, excluded.approved)""",
                    (kind, value, ts, ts, int(approve)),
                )

    def latest_analysis(self) -> dict[str, Any] | None:
        with self._connect(readonly=True) as db:
            row = db.execute("SELECT * FROM llm_analyses ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return None
            value = dict(row)
            value["alert_ids"] = json.loads(value["alert_ids"])
            value["result_json"] = json.loads(value["result_json"]) if value["result_json"] else None
            return value

    def get_alerts(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self._connect(readonly=True) as db:
            alerts = [dict(row) for row in db.execute(
                "SELECT * FROM alerts ORDER BY CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC, ts DESC LIMIT ?", (limit,)
            )]
        for alert in alerts:
            alert["evidence"] = json.loads(alert["evidence"])
        return alerts

    def latest_run(self, kind: str) -> dict[str, Any] | None:
        with self._connect(readonly=True) as db:
            row = db.execute("SELECT * FROM runs WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["collectors"] = json.loads(value["collectors"]) if value["collectors"] else {}
        return value

    def backup(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect(readonly=True) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        return destination

    def purge(self, cutoff: str) -> dict[str, int]:
        deleted = {}
        statements = {
            "connections": "DELETE FROM connections WHERE ts<?",
            "auth_events": "DELETE FROM auth_events WHERE ts<?",
            "file_events": "DELETE FROM file_events WHERE ts<?",
            "firewall_events": "DELETE FROM firewall_events WHERE ts<?",
            "sysmon_events": "DELETE FROM sysmon_events WHERE ts<?",
            "llm_analyses": "DELETE FROM llm_analyses WHERE ts<?",
            "runs": "DELETE FROM runs WHERE started_at<? AND id NOT IN (SELECT run_id FROM llm_analyses WHERE run_id IS NOT NULL)",
            "alerts": "DELETE FROM alerts WHERE ts<? AND status!='confirmed'",
        }
        with self._connect() as db:
            for table, sql in statements.items():
                cursor = db.execute(sql, (cutoff,))
                deleted[table] = max(cursor.rowcount, 0)
        connection = self._connect()
        try:
            connection.isolation_level = None
            connection.execute("VACUUM")
        finally:
            connection.close()
        return deleted
