from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from domain.models import CollectionRequest, CollectionResult, FileEvent, NetworkConnection, SysmonEvent


CHANNEL = "Microsoft-Windows-Sysmon/Operational"


def parse_sysmon_xml(xml: str):
    root = ET.fromstring(xml)
    def local(tag): return tag.rsplit("}", 1)[-1]
    system = next(node for node in root if local(node.tag) == "System")
    event_id = int(next(node for node in system if local(node.tag) == "EventID").text)
    record_id = int(next(node for node in system if local(node.tag) == "EventRecordID").text)
    time_node = next(node for node in system if local(node.tag) == "TimeCreated")
    ts = datetime.fromisoformat(time_node.attrib["SystemTime"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    data = {}
    for node in root.iter():
        if local(node.tag) == "Data" and node.attrib.get("Name"):
            data[node.attrib["Name"]] = node.text or ""
    return ts, event_id, record_id, data


class SysmonCollector:
    def __init__(self, name: str, event_ids: tuple[int, ...], item_kind: str):
        self.name, self.event_ids, self.item_kind = name, event_ids, item_kind

    def _map(self, xml: str):
        ts, event_id, record_id, data = parse_sysmon_xml(xml)
        if self.item_kind == "connections":
            return NetworkConnection(
                ts, "sysmon", str(data.get("Protocol", "")).casefold() or None,
                "outbound" if data.get("Initiated", "").casefold() == "true" else "inbound",
                data.get("SourceIp"), _int(data.get("SourcePort")), data.get("DestinationIp"),
                _int(data.get("DestinationPort")), None, _int(data.get("ProcessId")),
                data.get("Image", "").rsplit("\\", 1)[-1] or None, data.get("Image"), data.get("User"),
            )
        if self.item_kind == "file_events":
            path = data.get("TargetFilename", "")
            hashes = data.get("Hashes", "")
            sha256 = next((part.split("=", 1)[1] for part in hashes.split(",") if part.startswith("SHA256=")), None)
            action = "created" if event_id == 11 else "deleted"
            return FileEvent(ts, "sysmon", action, path, extension=("." + path.rsplit(".", 1)[-1].casefold()) if "." in path else None,
                             sha256=sha256, process_name=data.get("Image"),
                             dedup_key=hashlib.sha256(f"sysmon|{record_id}".encode()).hexdigest())
        return SysmonEvent(ts, event_id, record_id, data.get("Image"), data)

    def collect(self, request: CollectionRequest) -> CollectionResult:
        try: import win32evtlog
        except ImportError:
            return CollectionResult(self.name, self.item_kind, (), "skipped", ("pywin32 no está instalado",))
        last = int((request.cursor or {}).get("record_id", 0))
        ids = " or ".join(f"EventID={value}" for value in self.event_ids)
        query = f"*[System[({ids})" + (f" and EventRecordID > {last}" if last else "") + "]]"
        items, warnings, maximum = [], [], last
        try:
            handle = win32evtlog.EvtQuery(CHANNEL, win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryForwardDirection, query)
            while True:
                events = win32evtlog.EvtNext(handle, 64)
                if not events: break
                for event in events:
                    try:
                        item = self._map(win32evtlog.EvtRender(event, win32evtlog.EvtRenderEventXml))
                        items.append(item)
                        maximum = max(maximum, parse_sysmon_xml(win32evtlog.EvtRender(event, win32evtlog.EvtRenderEventXml))[2])
                    except (ValueError, KeyError, ET.ParseError) as exc:
                        warnings.append(str(exc))
        except Exception as exc:
            return CollectionResult(self.name, self.item_kind, (), "skipped", (f"Sysmon no disponible: {exc}",))
        return CollectionResult(self.name, self.item_kind, tuple(items), "partial" if warnings else "ok", tuple(warnings), {"record_id": maximum})


def _int(value):
    try: return int(value) if value else None
    except ValueError: return None

