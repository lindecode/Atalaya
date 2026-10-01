from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from domain.models import CollectionResult
from infrastructure.sqlite.connection import connect
from infrastructure.sqlite.migrations import MIGRATIONS
from settings import Settings


TABLES = (
    "runs", "connections", "auth_events", "file_events", "firewall_events",
    "persistence_items", "baseline", "alerts", "llm_analyses", "cursors",
)


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
