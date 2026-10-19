# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from domain.models import CollectionRequest, CollectionResult, FirewallEvent


def packet_key(ts: str, action, proto, src_ip, src_port, dst_ip, dst_port) -> str:
    """Same packet, same key, whether read from pfirewall.log or from Security event 5152 (second precision)."""
    second = datetime.fromisoformat(ts).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    return hashlib.sha256("|".join(str(part) for part in (second, action, proto, src_ip, src_port, dst_ip, dst_port))
                          .encode("utf-8")).hexdigest()


def _integer(value: str | None) -> int | None:
    try: return int(value) if value and value != "-" else None
    except ValueError: return None


class FirewallLogCollector:
    name = "windows_firewall"

    def __init__(self, path: Path):
        self.path = path

    def collect(self, request: CollectionRequest) -> CollectionResult:
        try:
            stat = self.path.stat()
        except OSError as exc:
            return CollectionResult(self.name, "firewall_events", (), "skipped", (f"Firewall log no disponible: {exc}",))
        cursor = request.cursor or {}
        offset = int(cursor.get("offset", 0))
        if cursor.get("file_id") != stat.st_ino or stat.st_size < offset:
            offset = 0
        try:
            self.path.open("rb").close()
        except PermissionError:
            # MpsSvc recreates the file without the folder's read permission (see configurar-permisos.ps1)
            return CollectionResult(self.name, "firewall_events", (), "skipped", (
                "Sin permiso para leer el log del firewall: ejecute start\\configurar-permisos.bat",))
        fields = ["date", "time", "action", "protocol", "src-ip", "dst-ip", "src-port", "dst-port", "size", "tcpflags", "tcpsyn", "tcpack", "tcpwin", "icmptype", "icmpcode", "info", "path", "direction"]
        events = []
        warnings = []
        with self.path.open("r", encoding="utf-8-sig", errors="replace") as stream:
            stream.seek(offset)
            for line in stream:
                line = line.strip()
                if not line: continue
                if line.startswith("#Fields:"):
                    fields = line.removeprefix("#Fields:").strip().split()
                    continue
                if line.startswith("#"): continue
                values = line.split()
                if len(values) < len(fields):
                    warnings.append("Línea de firewall incompleta omitida")
                    continue
                row = dict(zip(fields, values))
                try:
                    # pfirewall.log writes local time; a naive datetime's astimezone() reads it as local
                    timestamp = datetime.fromisoformat(f"{row['date']}T{row['time']}").astimezone(timezone.utc).isoformat()
                except (KeyError, ValueError):
                    warnings.append("Fecha de firewall inválida")
                    continue
                proto = row.get("protocol", "").casefold() or None
                packet = (timestamp, row.get("action"), proto, row.get("src-ip"), _integer(row.get("src-port")),
                          row.get("dst-ip"), _integer(row.get("dst-port")))
                events.append(FirewallEvent(*packet, row.get("direction"), packet_key(*packet)))
            next_offset = stream.tell()
        return CollectionResult(self.name, "firewall_events", tuple(events), "partial" if warnings else "ok",
                                tuple(sorted(set(warnings))), {"offset": next_offset, "size": stat.st_size, "file_id": stat.st_ino})
