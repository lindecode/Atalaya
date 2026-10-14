from __future__ import annotations

from datetime import datetime, timezone

from domain import dev
from domain.models import EvidenceView
from domain.rules import catalog

NOW = datetime.now(timezone.utc).isoformat()


def _listen(port, address, process="node.exe", row_id=1):
    return {"id": row_id, "ts": NOW, "direction": "listen", "laddr": address, "lport": port, "process_name": process}


def test_runtime_scope_and_origin():
    assert dev.runtime("javaw.exe").label == "Java"
    assert dev.runtime("Node.EXE").key == "node"
    assert dev.runtime("app.exe", r"C:\Program Files\Java\jdk-21\bin\app.exe").key == "java"
    assert dev.runtime("explorer.exe") == dev.OTHER
    assert [dev.scope(a) for a in ("127.0.0.1", "::1", "0.0.0.0", "::", "192.168.1.5", "8.8.8.8")] == \
        ["local", "local", "all", "all", "lan", "all"]
    assert [dev.origin(a) for a in ("127.0.0.1", "::ffff:192.168.1.9", "10.0.0.2", "1.1.1.1", "0.0.0.0", "x")] == \
        ["local", "lan", "lan", "internet", None, None]


def test_command_lines_are_redacted_and_java_targets_found():
    redacted = dev.redact_command("java -Dspring.datasource.password=hunter2 -jar app.jar --token abc postgres://u:p@db/x")
    assert "hunter2" not in redacted and "abc" not in redacted and "u:p@" not in redacted
    assert dev.java_target(r'java -Xmx1g -jar "C:\apps\billing-1.2.jar" --port 8080') == "billing-1.2.jar"
    assert dev.java_target("java -cp lib/* com.acme.Main arg") == "com.acme.Main"
    assert dev.java_target("java -version") is None


def test_r18_debug_port_exposed_only_beyond_loopback_and_until_approved():
    view = EvidenceView(connections=(_listen(9229, "0.0.0.0"), _listen(9229, "127.0.0.1", row_id=2),
                                     _listen(3000, "0.0.0.0", row_id=3), _listen(5005, "::", "java.exe", 4)))
    alerts = catalog.r18(view, None)
    assert [alert.entity for alert in alerts] == ["node.exe|9229", "java.exe|5005"]
    approved = EvidenceView(connections=view.connections, baseline=frozenset({("debug_port", "node.exe|9229")}))
    assert [alert.entity for alert in catalog.r18(approved, None)] == ["java.exe|5005"]


def test_r19_pings_by_source_with_severity_by_network():
    ping = lambda ip, row_id: {"id": row_id, "ts": NOW, "action": "DROP", "proto": "icmp", "src_ip": ip,
                               "direction": "RECEIVE"}
    view = EvidenceView(firewall_events=(ping("192.168.1.1", 1), ping("192.168.1.1", 2), ping("45.1.2.3", 3),
                                         ping("127.0.0.1", 4),
                                         {**ping("192.168.1.7", 5), "proto": "tcp"}))
    alerts = {alert.entity: alert for alert in catalog.r19(view, None)}
    assert set(alerts) == {"192.168.1.1", "45.1.2.3"}
    assert alerts["192.168.1.1"].severity == "low" and alerts["192.168.1.1"].summary["count"] == 2
    assert alerts["45.1.2.3"].severity == "medium"


def test_r20_tunnel_tools_connected_to_the_internet():
    row = {"id": 1, "ts": NOW, "direction": "outbound", "raddr": "3.4.5.6", "rport": 443, "process_name": "ngrok.exe",
           "process_path": r"C:\tools\ngrok.exe"}
    lan = {**row, "id": 2, "raddr": "192.168.1.2"}
    assert [alert.entity for alert in catalog.r20(EvidenceView(connections=(row, lan)), None)] == ["ngrok"]
    approved = EvidenceView(connections=(row,), baseline=frozenset({("tunnel", r"c:\tools\ngrok.exe")}))
    assert catalog.r20(approved, None) == []
