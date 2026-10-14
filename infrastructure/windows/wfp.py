"""Packets the Windows Filtering Platform dropped (Security event 5152), as firewall events.

This is the reliable source of pings and port scans: reading Security only needs the "Event Log Readers" group,
while MpsSvc keeps resetting the permissions of pfirewall.log. configurar-permisos turns the audit on.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from domain.models import CollectionRequest, CollectionResult, FirewallEvent
from infrastructure.windows.common import is_windows
from infrastructure.windows.event_log import _access_denied, _local_name
from infrastructure.windows.firewall import packet_key

EVENT_ID = 5152
PROTOCOLS = {"1": "icmp", "6": "tcp", "17": "udp", "58": "icmp"}
INBOUND = "%%14592"
FIRST_LOOK_MS = 24 * 3600 * 1000   # without a cursor, only the last day: the channel can hold weeks
MAX_EVENTS = 20_000                 # one collection never floods the database (a scan can produce thousands)


def _port(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def parse(xml: str) -> tuple[int, FirewallEvent]:
    root = ET.fromstring(xml)
    system = next(child for child in root if _local_name(child.tag) == "System")
    record = int(next(node.text for node in system if _local_name(node.tag) == "EventRecordID"))
    created = next(node for node in system if _local_name(node.tag) == "TimeCreated").attrib["SystemTime"]
    ts = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    data = {node.attrib.get("Name"): node.text for node in root.iter() if _local_name(node.tag) == "Data"}
    proto = PROTOCOLS.get(str(data.get("Protocol")), str(data.get("Protocol") or "") or None)
    direction = "RECEIVE" if data.get("Direction") == INBOUND else "SEND"
    source, destination = data.get("SourceAddress"), data.get("DestAddress")
    source_port, destination_port = _port(data.get("SourcePort")), _port(data.get("DestPort"))
    if proto == "icmp":  # for ICMP the "ports" are the message type and code, not ports
        source_port = destination_port = None
    return record, FirewallEvent(ts, "DROP", proto, source, source_port, destination, destination_port, direction,
                                 packet_key(ts, "DROP", proto, source, source_port, destination, destination_port))


def _query(after: int | None) -> str:
    if after:
        return f"*[System[(EventID={EVENT_ID}) and (EventRecordID > {int(after)})]]"
    return f"*[System[(EventID={EVENT_ID}) and TimeCreated[timediff(@SystemTime) <= {FIRST_LOOK_MS}]]]"


def read(after: int | None, limit: int = MAX_EVENTS) -> tuple[list[FirewallEvent], int | None]:
    """Drops newer than record `after` (or from the last day), oldest first; returns them and the last record."""
    import win32evtlog
    handle = win32evtlog.EvtQuery("Security", win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryForwardDirection,
                                  _query(after))
    events, last = [], after
    while len(events) < limit:
        batch = win32evtlog.EvtNext(handle, 256)
        if not batch:
            break
        for event in batch:
            try:
                record, parsed = parse(win32evtlog.EvtRender(event, win32evtlog.EvtRenderEventXml))
            except (ValueError, KeyError, StopIteration, ET.ParseError):
                continue
            events.append(parsed)
            last = max(last or 0, record)
    return events, last


def latest_record() -> int | None:
    import win32evtlog
    handle = win32evtlog.EvtQuery("Security", win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection,
                                  f"*[System[(EventID={EVENT_ID})]]")
    batch = win32evtlog.EvtNext(handle, 1)
    if not batch:
        return 0
    return parse(win32evtlog.EvtRender(batch[0], win32evtlog.EvtRenderEventXml))[0]


class WfpDropCollector:
    name = "wfp_drops"

    def collect(self, request: CollectionRequest) -> CollectionResult:
        if not is_windows():
            return CollectionResult(self.name, "firewall_events", (), "skipped", ("Solo disponible en Windows",))
        try:
            events, last = read(int((request.cursor or {}).get("record_id", 0)) or None)
        except ImportError:
            return CollectionResult(self.name, "firewall_events", (), "skipped", ("pywin32 no está instalado",))
        except Exception as exc:  # pywin32 raises its own error type
            if _access_denied(exc):
                return CollectionResult(self.name, "firewall_events", (), "skipped", (
                    "Security sin permiso de lectura: ejecute start\\configurar-permisos.bat",))
            return CollectionResult(self.name, "firewall_events", (), "skipped", (f"Eventos 5152: {exc}",))
        warnings = (f"Más de {MAX_EVENTS} paquetes descartados: el resto se lee en el próximo ciclo",) \
            if len(events) >= MAX_EVENTS else ()
        return CollectionResult(self.name, "firewall_events", tuple(events), "partial" if warnings else "ok", warnings,
                                {"record_id": last or 0})


class WfpTail:
    """Live drops for the network watch; the first call only finds where the channel ends."""

    def __init__(self):
        self.after: int | None = None
        self.available = True

    def __call__(self, now_iso: str = "") -> list[dict]:
        from dataclasses import asdict
        try:
            if self.after is None:
                self.after = latest_record() or 0
                return []
            events, last = read(self.after, limit=2000)
            self.after = last or self.after
            self.available = True
            return [asdict(event) for event in events]
        except Exception:
            self.available = False
            return []
