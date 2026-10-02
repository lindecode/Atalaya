from infrastructure.windows.event_log import _parse_event


XML = """<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
<System><Provider Name="Microsoft-Windows-Security-Auditing"/><EventID>4625</EventID>
<TimeCreated SystemTime="2026-10-01T10:00:00.0000000Z"/><EventRecordID>42</EventRecordID></System>
<EventData><Data Name="TargetUserName">alice</Data><Data Name="IpAddress">192.0.2.10</Data>
<Data Name="LogonType">10</Data><Data Name="SubStatus">0xC000006A</Data></EventData></Event>"""


def test_parses_event_fields_by_name():
    event = _parse_event(XML, "Security")
    assert event.event_id == 4625
    assert event.record_id == 42
    assert event.target_user == "alice"
    assert event.source_ip == "192.0.2.10"
    assert event.logon_type == 10
    assert event.status_code == "0xC000006A"



def test_access_denied_is_skipped_with_a_hint_instead_of_requiring_admin(monkeypatch):
    import sys
    from types import SimpleNamespace

    from domain.models import CollectionRequest
    from infrastructure.windows import event_log

    class PyWinError(Exception):
        winerror = 5

    def denied(*args):
        raise PyWinError(5, "EvtQuery", "Acceso denegado.")

    monkeypatch.setattr(event_log, "is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "win32evtlog", SimpleNamespace(
        EvtQuery=denied, EvtQueryChannelPath=1, EvtQueryForwardDirection=0x100))
    collector = event_log.WindowsEventLogCollector("security_events", "Security", (4625,), requires_admin=True)

    result = collector.collect(CollectionRequest("2026-10-01T12:00:00+00:00"))

    assert result.status == "skipped"
    assert "configurar-permisos" in result.warnings[0]
