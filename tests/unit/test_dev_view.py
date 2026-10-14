from __future__ import annotations

from application import dev_view

SNAPSHOT = {
    "taken_at": "2026-10-14T12:00:00+00:00",
    "connections": [
        {"direction": "listen", "laddr": "::", "lport": 8080, "pid": 10, "process_name": "java.exe"},
        {"direction": "listen", "laddr": "0.0.0.0", "lport": 8080, "pid": 10, "process_name": "java.exe"},
        {"direction": "listen", "laddr": "127.0.0.1", "lport": 5173, "pid": 20, "process_name": "node.exe"},
        {"direction": "listen", "laddr": "0.0.0.0", "lport": 9229, "pid": 20, "process_name": "node.exe"},
        {"direction": "listen", "laddr": "0.0.0.0", "lport": 135, "pid": 4, "process_name": None},
        {"direction": "listen", "laddr": "127.0.0.1", "lport": 6850, "pid": 30, "process_name": "Lights.exe"},
        {"direction": "inbound", "laddr": "192.168.1.10", "lport": 8080, "raddr": "192.168.1.20", "rport": 50000,
         "pid": 10, "process_name": "java.exe"},
        {"direction": "inbound", "laddr": "192.168.1.10", "lport": 8080, "raddr": "8.8.8.8", "rport": 50001,
         "pid": 10, "process_name": "java.exe"},
        {"direction": "inbound", "laddr": "127.0.0.1", "lport": 5173, "raddr": "127.0.0.1", "rport": 50002,
         "pid": 20, "process_name": "node.exe"},
    ],
    "processes": [
        {"pid": 10, "name": "java.exe", "path": None, "ppid": 1, "parent": "idea64.exe", "memory_mb": 900,
         "started": "2026-10-14T10:00:00+00:00", "command": "java -jar app.jar", "target": "app.jar"},
        {"pid": 20, "name": "node.exe", "path": None, "ppid": 1, "parent": "Code.exe", "memory_mb": 150,
         "started": "2026-10-14T11:00:00+00:00", "command": "node --inspect=0.0.0.0:9229 server.js", "target": None},
    ],
}


def test_servers_merge_addresses_take_the_widest_reach_and_hide_noise():
    rows = dev_view.servers(SNAPSHOT)
    assert [(row["port"], row["scope"]) for row in rows] == [(8080, "all"), (9229, "all"), (5173, "local")]
    java = rows[0]
    assert java["addresses"] == ["::", "0.0.0.0"] and java["target"] == "app.jar" and java["language"] == "Java"
    assert [client["origin"] for client in java["clients"]] == ["lan", "internet"]
    assert rows[1]["debug"] == "Inspector de Node.js"
    everything = {row["port"] for row in dev_view.servers(SNAPSHOT, include_all=True)}
    assert {135, 6850} <= everything  # Windows RPC and a vendor helper only with "all servers"


def test_runtimes_group_processes_with_their_ports():
    groups = {group["language"]: group for group in dev_view.runtimes(SNAPSHOT)}
    assert set(groups) == {"Java", "Node.js"}
    assert groups["Node.js"]["processes"][0]["ports"] == [5173, 9229]
    assert groups["Java"]["memory_mb"] == 900


def test_graph_places_servers_and_external_clients_and_keeps_past_clients_dashed():
    rows = dev_view.servers(SNAPSHOT)
    history = [{"kind": "client", "remote_ip": "45.1.2.3", "lport": 8080, "network": "internet"},
               {"kind": "ping", "remote_ip": "192.168.1.1", "lport": None, "network": "lan"}]
    graph = dev_view.graph(rows, history)
    ids = {node["id"] for node in graph["nodes"]}
    assert {"host", "s:8080:java.exe", "c:192.168.1.20", "c:8.8.8.8", "c:45.1.2.3"} <= ids
    assert "c:127.0.0.1" not in ids                                  # localhost clients hidden by default
    dashed = [edge for edge in graph["edges"] if edge.get("dashed")]
    assert [(edge["from"], edge["to"]) for edge in dashed] == [("c:45.1.2.3", "s:8080:java.exe")]
    assert "c:127.0.0.1" in {node["id"] for node in dev_view.graph(rows, include_local_clients=True)["nodes"]}
    assert all("_angle" not in row for row in rows)
