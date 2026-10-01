from __future__ import annotations

from domain.models import CollectionRequest, EvidenceView
from domain.rules.catalog import r12
from infrastructure.windows.firewall import FirewallLogCollector
from settings import Settings


def test_incremental_firewall_and_port_scan(tmp_path):
    log = tmp_path / "pfirewall.log"
    header = "#Fields: date time action protocol src-ip dst-ip src-port dst-port direction\n"
    lines = [f"2026-10-01 12:00:{i:02d} DROP TCP 203.0.113.9 10.0.0.1 5000 {1000+i} RECEIVE" for i in range(20)]
    log.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    collector = FirewallLogCollector(log)
    first = collector.collect(CollectionRequest("2026-10-01T12:01:00+00:00"))
    second = collector.collect(CollectionRequest("2026-10-01T12:02:00+00:00", first.next_cursor))

    assert len(first.items) == 20
    assert second.items == ()
    view = EvidenceView(firewall_events=tuple({**item.__dict__, "id": index} if hasattr(item, "__dict__") else {
        "id": index, "ts": item.ts, "action": item.action, "src_ip": item.src_ip, "dst_port": item.dst_port
    } for index, item in enumerate(first.items)))
    assert r12(view, Settings())[0].rule_id == "R12"

