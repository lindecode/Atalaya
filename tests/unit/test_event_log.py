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

