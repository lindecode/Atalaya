from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from domain.models import CollectionRequest, CollectionResult, FirewallEvent


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
                    timestamp = datetime.fromisoformat(f"{row['date']}T{row['time']}").replace(tzinfo=timezone.utc).isoformat()
                except (KeyError, ValueError):
                    warnings.append("Fecha de firewall inválida")
                    continue
                events.append(FirewallEvent(
                    timestamp, row.get("action"), row.get("protocol", "").casefold() or None,
                    row.get("src-ip"), _integer(row.get("src-port")), row.get("dst-ip"),
                    _integer(row.get("dst-port")), row.get("direction"),
                    hashlib.sha256("|".join(values).encode("utf-8")).hexdigest(),
                ))
            next_offset = stream.tell()
        return CollectionResult(self.name, "firewall_events", tuple(events), "partial" if warnings else "ok",
                                tuple(sorted(set(warnings))), {"offset": next_offset, "size": stat.st_size, "file_id": stat.st_ino})
