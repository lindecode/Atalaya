from __future__ import annotations

from datetime import datetime, timezone

from infrastructure.windows import wfp
from infrastructure.windows.firewall import FirewallLogCollector, packet_key
from domain.models import CollectionRequest

EVENT = """<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
<System><Provider Name="Microsoft-Windows-Security-Auditing"/><EventID>5152</EventID>
<TimeCreated SystemTime="2026-10-14T22:10:05.1234567Z"/><EventRecordID>{record}</EventRecordID></System>
<EventData><Data Name="ProcessId">0</Data><Data Name="Application">-</Data><Data Name="Direction">{direction}</Data>
<Data Name="SourceAddress">{source}</Data><Data Name="SourcePort">{sport}</Data>
<Data Name="DestAddress">192.168.1.10</Data><Data Name="DestPort">{dport}</Data>
<Data Name="Protocol">{proto}</Data><Data Name="FilterRTID">0</Data></EventData></Event>"""


def test_parse_inbound_ping_and_tcp_probe():
    record, ping = wfp.parse(EVENT.format(record=7, direction="%%14592", source="192.168.1.1", sport=8, dport=0, proto=1))
    assert record == 7
    assert (ping.action, ping.proto, ping.src_ip, ping.src_port, ping.dst_port, ping.direction) == \
        ("DROP", "icmp", "192.168.1.1", None, None, "RECEIVE")      # ICMP type/code are not ports
    _, probe = wfp.parse(EVENT.format(record=8, direction="%%14592", source="45.1.2.3", sport=51000, dport=3389, proto=6))
    assert (probe.proto, probe.src_port, probe.dst_port) == ("tcp", 51000, 3389)
    _, outgoing = wfp.parse(EVENT.format(record=9, direction="%%14593", source="192.168.1.10", sport=5000, dport=53, proto=17))
    assert (outgoing.proto, outgoing.direction) == ("udp", "SEND")
    assert ping.ts.startswith("2026-10-14T22:10:05")


def test_the_same_packet_has_the_same_key_from_both_sources(tmp_path):
    _, probe = wfp.parse(EVENT.format(record=8, direction="%%14592", source="45.1.2.3", sport=51000, dport=3389, proto=6))
    local = datetime.fromisoformat("2026-10-14T22:10:05+00:00").astimezone()  # pfirewall.log writes local time
    log = tmp_path / "pfirewall.log"
    log.write_text("#Fields: date time action protocol src-ip dst-ip src-port dst-port size tcpflags tcpsyn tcpack "
                   "tcpwin icmptype icmpcode info path\n"
                   f"{local:%Y-%m-%d %H:%M:%S} DROP TCP 45.1.2.3 192.168.1.10 51000 3389 52 S 0 0 0 - - - RECEIVE\n",
                   encoding="utf-8")
    from_file = FirewallLogCollector(log).collect(CollectionRequest(datetime.now(timezone.utc).isoformat())).items[0]
    assert from_file.dedup_key == probe.dedup_key
    assert packet_key(probe.ts, "DROP", "tcp", "45.1.2.3", 51000, "192.168.1.10", 3390) != probe.dedup_key


def test_queries_limit_the_first_look_and_resume_after_the_cursor():
    assert "timediff(@SystemTime) <= 86400000" in wfp._query(None)
    assert "EventRecordID > 42" in wfp._query(42)
