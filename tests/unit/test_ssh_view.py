from __future__ import annotations

from application import ssh_view

HISTORY = [
    {"remote_address": "187.77.15.126", "remote_port": 2222, "direction": "outbound", "process_name": "ssh.exe",
     "tunnel_types": "socks", "agent_forwarding": 0, "local_port": None, "first_seen": "2026-10-14T10:00:00+00:00",
     "last_seen": "2026-10-14T20:00:00+00:00"},
    {"remote_address": "10.0.0.5", "remote_port": 22, "direction": "outbound", "process_name": "ssh.exe",
     "tunnel_types": "reverse,local", "agent_forwarding": 1, "local_port": None, "first_seen": "2026-10-13T08:00:00+00:00",
     "last_seen": "2026-10-13T09:00:00+00:00"},
    {"remote_address": "127.0.0.1", "remote_port": 63251, "direction": "outbound", "process_name": "chrome.exe",
     "tunnel_types": None, "agent_forwarding": 0, "local_port": None, "first_seen": "x", "last_seen": "x"},
    {"remote_address": "192.168.1.40", "remote_port": 51000, "direction": "inbound", "process_name": "wslrelay.exe",
     "tunnel_types": None, "agent_forwarding": 0, "local_port": 22, "first_seen": "2026-10-14T11:00:00+00:00",
     "last_seen": "2026-10-14T11:05:00+00:00"},
]
SNAPSHOT = {"taken_at": "2026-10-14T20:30:00+00:00", "processes": [], "connections": [
    {"direction": "outbound", "raddr": "187.77.15.126", "rport": 2222, "pid": 7, "process_name": "ssh.exe"},
    {"direction": "listen", "laddr": "0.0.0.0", "lport": 63251, "pid": 7, "process_name": "ssh.exe"},
    {"direction": "inbound", "laddr": "127.0.0.1", "lport": 63251, "raddr": "127.0.0.1", "pid": 7, "process_name": "ssh.exe"},
    {"direction": "inbound", "laddr": "127.0.0.1", "lport": 63251, "raddr": "127.0.0.1", "pid": 7, "process_name": "ssh.exe"},
]}


def test_sessions_tunnels_listeners_and_risks():
    data = ssh_view.model(HISTORY, SNAPSHOT, {"187.77.15.126": "vps.example"})
    socks, old = data["sessions"]
    assert (socks["remote"], socks["name"], socks["live"], socks["tunnels"]) == ("187.77.15.126", "vps.example", True, ["socks"])
    assert socks["listeners"] == [{"port": 63251, "address": "0.0.0.0", "scope": "all", "users": 2}]
    assert [r["severity"] for r in socks["risks"]] == ["high"]                 # the SOCKS port listens on the network
    assert (old["live"], old["tunnels"], old["agent_forwarding"]) == (False, ["local", "reverse"], True)
    assert [r["severity"] for r in old["risks"]] == ["high", "medium"]         # -R and -A
    assert [(i["remote"], i["port"], i["origin"]) for i in data["inbound"]] == [("192.168.1.40", 22, "lan")]
    assert all(s["remote"] != "127.0.0.1" for s in data["sessions"])          # local apps using the proxy are not servers


def test_graph_links_tunnel_ports_between_pc_and_server():
    graph = ssh_view.graph(ssh_view.model(HISTORY, SNAPSHOT))
    ids = {node["id"] for node in graph["nodes"]}
    assert {"host", "s:187.77.15.126:2222", "s:10.0.0.5:22", "t:63251", "i:192.168.1.40:22"} <= ids
    pairs = {(edge["from"], edge["to"]): edge for edge in graph["edges"]}
    assert ("t:63251", "s:187.77.15.126:2222") in pairs and ("host", "t:63251") in pairs
    assert pairs[("host", "s:10.0.0.5:22")]["dashed"] and not pairs[("host", "s:187.77.15.126:2222")]["dashed"]
