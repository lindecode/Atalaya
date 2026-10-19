# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
SNAPSHOT = {"taken_at": "2026-10-14T20:30:00+00:00", "processes": [
    {"pid": 7, "name": "ssh.exe", "ssh": {"destination": "vps", "port": 2222, "forwards": [
        {"kind": "dynamic", "bind": "0.0.0.0", "listen": 63251, "target": None}]}}],
    "ssh_config": [], "vscode_forwards": [], "connections": [
    {"direction": "outbound", "raddr": "187.77.15.126", "rport": 2222, "pid": 7, "process_name": "ssh.exe"},
    {"direction": "listen", "laddr": "0.0.0.0", "lport": 63251, "pid": 7, "process_name": "ssh.exe"},
    {"direction": "inbound", "laddr": "127.0.0.1", "lport": 63251, "raddr": "127.0.0.1", "pid": 7, "process_name": "ssh.exe"},
    {"direction": "inbound", "laddr": "127.0.0.1", "lport": 63251, "raddr": "127.0.0.1", "pid": 7, "process_name": "ssh.exe"},
]}


def test_sessions_tunnels_listeners_and_risks():
    data = ssh_view.model(HISTORY, SNAPSHOT, {"187.77.15.126": "vps.example"})
    socks, old = data["sessions"]
    assert (socks["remote"], socks["name"], socks["live"], socks["tunnels"]) == ("187.77.15.126", "vps.example", True, ["socks"])
    assert [(f["kind"], f["listen"], f["scope"], f["users"], f["via"]) for f in socks["forwards"]] == [
        ("dynamic", 63251, "all", 2, "ssh")]
    assert socks["alias"] == "vps"
    assert [r["severity"] for r in socks["risks"]] == ["high"]                 # the SOCKS port listens on the network
    assert (old["live"], old["tunnels"], old["agent_forwarding"]) == (False, ["local", "reverse"], True)
    assert [r["severity"] for r in old["risks"]] == ["high", "medium"]         # -R and -A
    assert [(i["remote"], i["port"], i["origin"]) for i in data["inbound"]] == [("192.168.1.40", 22, "lan")]
    assert all(s["remote"] != "127.0.0.1" for s in data["sessions"])          # local apps using the proxy are not servers


def test_graph_links_tunnel_ports_between_pc_and_server():
    graph = ssh_view.graph(ssh_view.model(HISTORY, SNAPSHOT))
    ids = {node["id"] for node in graph["nodes"]}
    tunnel = "t:187.77.15.126:2222:dynamic:63251"
    assert {"host", "s:187.77.15.126:2222", "s:10.0.0.5:22", tunnel, "i:192.168.1.40:22"} <= ids
    pairs = {(edge["from"], edge["to"]): edge for edge in graph["edges"]}
    assert (tunnel, "s:187.77.15.126:2222") in pairs and ("host", tunnel) in pairs
    assert pairs[("host", "s:10.0.0.5:22")]["dashed"] and not pairs[("host", "s:187.77.15.126:2222")]["dashed"]


def test_vscode_and_config_forwards_are_tied_to_the_live_session():
    from domain.ssh_forwards import parse_config
    config = parse_config("Host vps\n  HostName 187.77.15.126\n  Port 2222\n  LocalForward 9000 db.internal:5432\n"
                          "Host *\n  RemoteForward 2201 localhost:22\n")
    snapshot = {**SNAPSHOT, "ssh_config": config, "vscode_forwards": [
        {"kind": "local", "listen": 8090, "bind": None, "target": "localhost:8090", "host": "vps", "auto": True},
        {"kind": "local", "listen": 3000, "bind": None, "target": "localhost:3000", "host": "vps", "auto": False},
        {"kind": "local", "listen": 7000, "bind": None, "target": "localhost:7000", "host": "otro", "auto": True}],
        "connections": SNAPSHOT["connections"] + [
            {"direction": "listen", "laddr": "127.0.0.1", "lport": 8090, "pid": 30, "process_name": "Code.exe"},
            {"direction": "listen", "laddr": "127.0.0.1", "lport": 9000, "pid": 7, "process_name": "ssh.exe"},
            {"direction": "inbound", "laddr": "127.0.0.1", "lport": 8090, "raddr": "127.0.0.1", "pid": 30,
             "process_name": "Code.exe"}]}
    session = ssh_view.model(HISTORY, snapshot)["sessions"][0]
    found = {(f["kind"], f["listen"]): f for f in session["forwards"]}
    assert set(found) == {("dynamic", 63251), ("local", 9000), ("remote", 2201), ("local", 8090)}
    assert found[("local", 8090)]["via"] == "VS Code (automático)" and found[("local", 8090)]["users"] == 1
    assert found[("local", 9000)]["target"] == "db.internal:5432" and found[("local", 9000)]["via"] == "~/.ssh/config"
    assert "reverse" in session["tunnels"]                     # RemoteForward from "Host *" applies too
    assert ssh_view.forward_for_port(snapshot, 8090)[0] == "vps"
    assert ssh_view.forward_for_port(snapshot, 3000) is None  # saved by VS Code but not open now
