from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from domain.models import EvidenceView
from domain.rules import catalog


NOW = datetime.now(timezone.utc)
CFG = SimpleNamespace(mass_file_count=100, mass_file_minutes=1, anomalous_extension_count=20, port_scan_count=20,
                      mass_file_exclude_dirs=(r"C:\Users\me\AppData\Local\Temp",))


def ts(seconds=0):
    return (NOW + timedelta(seconds=seconds)).isoformat()


def test_r09_uses_destination_extension_and_ignores_plain_readme():
    renames = tuple({"id": i, "ts": ts(i), "action": "moved", "path": f"C:\\d\\f{i}.jpg",
                     "dest_path": f"C:\\d\\f{i}.jpg.locked"} for i in range(20))
    assert any(a.title == "Extensión anómala masiva" and a.entity == ".locked" for a in catalog.r09(EvidenceView(file_events=renames), CFG))

    downloads = tuple({"id": i, "ts": ts(i), "action": "moved", "path": f"C:\\d\\f{i}.crdownload",
                       "dest_path": f"C:\\d\\f{i}.pdf"} for i in range(20))
    assert catalog.r09(EvidenceView(file_events=downloads), CFG) == []

    readme = ({"id": 1, "ts": ts(), "action": "observed_new", "path": r"C:\Users\me\Downloads\repo\README.md"},
              {"id": 2, "ts": ts(), "action": "observed_new", "path": r"C:\Users\me\Downloads\tool\readme.txt"})
    assert catalog.r09(EvidenceView(file_events=readme), CFG) == []

    spread = tuple({"id": i, "ts": ts(i), "action": "created", "path": f"C:\\Users\\me\\Documents\\d{i}\\README.txt"} for i in range(3))
    assert any(a.title == "Misma nota en varias carpetas" for a in catalog.r09(EvidenceView(file_events=spread), CFG))


def test_r08_ignores_temp_churn():
    temp = tuple({"id": i, "ts": ts(i // 2), "action": "modified", "path": f"C:\\Users\\me\\AppData\\Local\\Temp\\x{i}"} for i in range(150))
    assert catalog.r08(EvidenceView(file_events=temp), CFG) == []


def test_r12_finds_a_scan_after_a_noisy_first_window():
    noise = [{"id": i, "ts": ts(i), "action": "DROP", "src_ip": "203.0.113.9", "dst_port": 445} for i in range(25)]
    scan = [{"id": 100 + i, "ts": ts(600 + i), "action": "DROP", "src_ip": "203.0.113.9", "dst_port": 2000 + i} for i in range(20)]
    assert catalog.r12(EvidenceView(firewall_events=tuple(noise + scan)), CFG)


@pytest.mark.parametrize("ip", [None, "-", "::1"])
def test_r04_ignores_logons_without_a_real_source(ip):
    event = {"id": 1, "ts": ts(), "event_id": 4624, "logon_type": 3, "source_ip": ip, "target_user": "alice"}
    assert catalog.r04(EvidenceView(auth_events=(event,)), CFG) == []
