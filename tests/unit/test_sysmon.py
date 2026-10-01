from infrastructure.windows.sysmon import SysmonCollector, parse_sysmon_xml


XML = """<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>
<EventID>3</EventID><TimeCreated SystemTime="2026-10-01T12:00:00Z"/><EventRecordID>77</EventRecordID>
</System><EventData><Data Name="Image">C:\\Windows\\x.exe</Data><Data Name="ProcessId">123</Data>
<Data Name="Protocol">tcp</Data><Data Name="SourceIp">10.0.0.1</Data><Data Name="SourcePort">5000</Data>
<Data Name="DestinationIp">8.8.8.8</Data><Data Name="DestinationPort">443</Data><Data Name="Initiated">true</Data></EventData></Event>"""


def test_sysmon_network_mapping():
    ts, event_id, record_id, data = parse_sysmon_xml(XML)
    assert (event_id, record_id, data["DestinationIp"]) == (3, 77, "8.8.8.8")
    item = SysmonCollector("network", (3,), "connections")._map(XML)
    assert item.source == "sysmon"
    assert item.direction == "outbound"
    assert item.process_name == "x.exe"

