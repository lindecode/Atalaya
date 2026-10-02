from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from domain.models import AuthEvent, CollectionRequest, CollectionResult
from infrastructure.windows.common import is_windows


SECURITY_CHANNEL = "Security"
RDP_CHANNEL = "Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_event(xml: str, channel: str) -> AuthEvent:
    root = ET.fromstring(xml)
    system = next(child for child in root if _local_name(child.tag) == "System")
    event_data = next((child for child in root if _local_name(child.tag) in {"EventData", "UserData"}), None)
    system_values = {_local_name(node.tag): (node.text or "") for node in system}
    time_node = next((node for node in system if _local_name(node.tag) == "TimeCreated"), None)
    created = time_node.attrib.get("SystemTime", "") if time_node is not None else ""
    if created:
        created = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()

    data: dict[str, str] = {}
    if event_data is not None:
        for node in event_data.iter():
            name = node.attrib.get("Name") or _local_name(node.tag)
            if node.text and name not in {"EventData", "UserData"}:
                data[name] = node.text

    logon_type = data.get("LogonType")
    status = data.get("SubStatus") or data.get("Status")
    return AuthEvent(
        ts=created or datetime.now(timezone.utc).isoformat(),
        channel=channel,
        event_id=int(system_values["EventID"]),
        record_id=int(system_values["EventRecordID"]),
        logon_type=int(logon_type) if logon_type and logon_type.isdigit() else None,
        target_user=data.get("TargetUserName") or data.get("Param1"),
        source_ip=data.get("IpAddress") or data.get("ClientAddress"),
        source_host=data.get("WorkstationName") or data.get("ClientName"),
        process_name=data.get("ProcessName"),
        status_code=status,
        raw_xml=xml,
    )


def _access_denied(exc: Exception) -> bool:
    code = getattr(exc, "winerror", None)
    if code is None and getattr(exc, "args", None):
        code = exc.args[0]
    return code == 5  # ERROR_ACCESS_DENIED


class WindowsEventLogCollector:
    def __init__(self, name: str, channel: str, event_ids: tuple[int, ...], requires_admin: bool = False):
        self.name = name
        self.channel = channel
        self.event_ids = event_ids
        self.requires_admin = requires_admin

    def collect(self, request: CollectionRequest) -> CollectionResult:
        if not is_windows():
            return CollectionResult(self.name, "auth_events", (), "skipped", ("Solo disponible en Windows",))
        # No exigir administrador: el grupo "Lectores del registro de eventos" basta para leer Security
        # (start\configurar-permisos.bat). Si Windows niega el acceso, se omite con la pista de cómo darlo.
        try:
            import win32evtlog
        except ImportError:
            return CollectionResult(self.name, "auth_events", (), "skipped", ("pywin32 no está instalado",))

        last_record = int((request.cursor or {}).get("record_id", 0))
        ids = " or ".join(f"EventID={event_id}" for event_id in self.event_ids)
        record_filter = f" and EventRecordID > {last_record}" if last_record else ""
        query = f"*[System[({ids}){record_filter}]]"
        items: list[AuthEvent] = []
        warnings: list[str] = []
        maximum = last_record
        def read(query_text: str) -> None:
            nonlocal maximum
            handle = win32evtlog.EvtQuery(
                self.channel,
                win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryForwardDirection,
                query_text,
            )
            while True:
                events = win32evtlog.EvtNext(handle, 64)
                if not events:
                    break
                for event in events:
                    try:
                        parsed = _parse_event(win32evtlog.EvtRender(event, win32evtlog.EvtRenderEventXml), self.channel)
                        items.append(parsed)
                        maximum = max(maximum, parsed.record_id)
                    except (ValueError, ET.ParseError, KeyError) as exc:
                        warnings.append(f"Evento omitido por XML inválido: {exc}")

        try:
            read(query)
        except Exception as exc:  # pywin32 exposes platform-specific exception classes
            if _access_denied(exc):
                return CollectionResult(self.name, "auth_events", (), "skipped", (
                    f"{self.channel} sin permiso de lectura: ejecute start\\configurar-permisos.bat "
                    "o use una sesión de administrador",))
            if last_record:
                warnings.append(f"Cursor inválido o canal reiniciado; relectura desde el inicio: {exc}")
                items.clear()
                maximum = 0
                try:
                    read(f"*[System[({ids})]]")
                except Exception as retry_exc:
                    return CollectionResult(self.name, "auth_events", (), "skipped", tuple(warnings + [str(retry_exc)]))
            else:
                return CollectionResult(self.name, "auth_events", (), "skipped", (str(exc),))

        return CollectionResult(
            self.name, "auth_events", tuple(items), "partial" if warnings else "ok", tuple(warnings), {"record_id": maximum}
        )
