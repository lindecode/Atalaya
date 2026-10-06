from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from domain.models import EvidenceView
from domain.rules import catalog


BASE = datetime(2026, 10, 1, tzinfo=timezone.utc)
CFG = SimpleNamespace(
    brute_force_count=10, brute_force_minutes=5, mass_file_count=100,
    mass_file_minutes=1, anomalous_extension_count=20, port_scan_count=20,
    suspicious_ports=(4444, 1337, 31337, 6667, 5555, 9001),
    process_growth_mb=1024, process_high_memory_percent=25.0,
)


def ts(seconds=0):
    return (BASE + timedelta(seconds=seconds)).isoformat()


def auth(i, event_id, **values):
    return {"id": i, "ts": ts(i), "event_id": event_id, "source_ip": None,
            "target_user": None, "logon_type": None, **values}


def test_r01_boundary_and_negative():
    nine = tuple(auth(i, 4625, source_ip="192.0.2.2", target_user="alice") for i in range(9))
    ten = nine + (auth(9, 4625, source_ip="192.0.2.2", target_user="alice"),)
    assert catalog.r01(EvidenceView(auth_events=nine), CFG) == []
    assert any(a.rule_id == "R01" for a in catalog.r01(EvidenceView(auth_events=ten), CFG))


def test_numeric_rule_boundaries():
    files_99 = tuple({"id": i, "ts": ts(i // 2), "action": "modified", "path": f"x{i}"} for i in range(99))
    assert catalog.r08(EvidenceView(file_events=files_99), CFG) == []
    renamed_19 = tuple({"id": i, "ts": ts(i), "action": "moved", "path": f"x{i}.locked", "extension": ".locked"} for i in range(19))
    assert catalog.r09(EvidenceView(file_events=renamed_19), CFG) == []
    drops_19 = tuple({"id": i, "ts": ts(i), "action": "DROP", "src_ip": "203.0.113.4", "dst_port": 2000 + i} for i in range(19))
    assert catalog.r12(EvidenceView(firewall_events=drops_19), CFG) == []


@pytest.mark.parametrize(("rule", "view", "rule_id"), [
    (catalog.r02, EvidenceView(auth_events=tuple(auth(i, 4625, source_ip="198.51.100.2") for i in range(10)) + (auth(20, 4624, source_ip="198.51.100.2"),)), "R02"),
    (catalog.r03, EvidenceView(auth_events=(auth(1, 4624, source_ip="8.8.8.8", logon_type=10),)), "R03"),
    (catalog.r04, EvidenceView(auth_events=(auth(1, 4624, source_ip="10.0.0.2", target_user="alice", logon_type=3),)), "R04"),
    (catalog.r05, EvidenceView(connections=({"id": 1, "ts": ts(), "direction": "listen", "process_name": "x", "lport": 9999, "laddr": "0.0.0.0"},)), "R05"),
    (catalog.r06, EvidenceView(connections=({"id": 1, "ts": ts(), "raddr": "8.8.8.8", "process_path": r"C:\Users\me\Downloads\x.exe"},)), "R06"),
    (catalog.r07, EvidenceView(connections=({"id": 1, "ts": ts(), "direction": "outbound", "raddr": "8.8.8.8", "rport": 4444},)), "R07"),
    (catalog.r08, EvidenceView(file_events=tuple({"id": i, "ts": ts(i // 2), "action": "modified", "path": f"x{i}"} for i in range(100))), "R08"),
    (catalog.r09, EvidenceView(file_events=({"id": 1, "ts": ts(), "action": "created", "path": r"C:\README_DECRYPT.txt", "extension": ".txt"},)), "R09"),
    (catalog.r10, EvidenceView(persistence_items=({"id": 1, "first_seen": ts(), "kind": "run_key", "name": "x", "location": "HKCU", "command": "x", "active": 1},)), "R10"),
    (catalog.r11, EvidenceView(file_events=({"id": 1, "ts": ts(), "action": "created", "path": r"C:\Users\me\x.ps1", "extension": ".ps1", "sha256": "a"},)), "R11"),
    (catalog.r12, EvidenceView(firewall_events=tuple({"id": i, "ts": ts(i), "action": "DROP", "src_ip": "203.0.113.3", "dst_port": 1000 + i} for i in range(20))), "R12"),
    (catalog.r13, EvidenceView(auth_events=(auth(1, 1102),)), "R13"),
    (catalog.r14, EvidenceView(auth_events=(auth(1, 4732, target_user="alice"),)), "R14"),
    (catalog.r15, EvidenceView(process_snapshots=(
        {"id": 1, "ts": ts(), "process_key": "p", "name": "leak.exe", "private_bytes": 10, "rss_bytes": 10},
        {"id": 2, "ts": ts(60), "process_key": "p", "name": "leak.exe", "private_bytes": 2 * 1024**3, "rss_bytes": 2 * 1024**3},)), "R15"),
    (catalog.r16, EvidenceView(process_snapshots=(
        {"id": 1, "ts": ts(), "process_key": "p", "name": "x.exe", "path": r"C:\Users\me\Downloads\x.exe",
         "parent_name": "powershell.exe", "memory_percent": 1, "private_bytes": 10},)), "R16"),
])
def test_each_rule_has_trigger(rule, view, rule_id):
    assert any(alert.rule_id == rule_id for alert in rule(view, CFG))


@pytest.mark.parametrize("rule", [catalog.r02, catalog.r03, catalog.r04, catalog.r05, catalog.r06,
                                   catalog.r07, catalog.r08, catalog.r09, catalog.r10, catalog.r11,
                                   catalog.r12, catalog.r13, catalog.r14, catalog.r15, catalog.r16])
def test_each_rule_has_negative_case(rule):
    assert rule(EvidenceView(), CFG) == []
