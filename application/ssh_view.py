# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""SSH map model: the servers this computer connects to, the tunnels it opens, and who connects to its own SSH (pure).

History comes from ssh_observations (the collector keeps only flags such as -L/-R/-D/-A, never destinations from the
command line); "connected now" and the tunnel listeners come from the live sockets.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from domain import dev
from domain.ssh_forwards import host_settings

SSH_CLIENTS = {"ssh.exe", "scp.exe", "sftp.exe", "ssh", "scp", "sftp"}
TUNNEL_LABELS = {"local": ("Túnel local (-L)", "Local tunnel (-L)"), "reverse": ("Túnel inverso (-R)", "Reverse tunnel (-R)"),
                 "socks": ("Proxy SOCKS (-D)", "SOCKS proxy (-D)")}
ORIGIN_COLORS = {"lan": "#3b82f6", "internet": "#ef4444", "local": "#94a3b8"}
RISK_COLORS = {"high": "#ef4444", "medium": "#f59e0b"}
FORWARD_KINDS = {"local": ("Local (-L)", "Local (-L)"), "remote": ("Inverso (-R)", "Reverse (-R)"),
                 "dynamic": ("SOCKS (-D)", "SOCKS (-D)")}


def _client(name) -> bool:
    return str(name or "").casefold() in SSH_CLIENTS


def forwards(snapshot: dict) -> tuple[dict[tuple, list[dict]], dict[tuple, str]]:
    """Live tunnels per SSH session {(server, port): [...]} and the host alias of each session.

    Sources: the ssh command line (-L/-R/-D, -o LocalForward…), ~/.ssh/config for the alias it connected to, and the
    ports VS Code Remote-SSH forwards for that alias. A local forward is active when something listens on its port now.
    """
    rows = snapshot.get("connections", [])
    listening = defaultdict(list)
    for r in rows:
        if r.get("direction") == "listen" and r.get("lport") is not None:
            listening[r["lport"]].append(r)
    users = Counter(r.get("lport") for r in rows if r.get("direction") == "inbound")
    found: dict[tuple, list[dict]] = defaultdict(list)
    aliases: dict[tuple, str] = {}
    by_alias: dict[str, tuple] = {}

    def add(key, item, via):
        if any((f["kind"], f["listen"]) == (item["kind"], item["listen"]) for f in found[key]):
            return
        here = listening.get(item["listen"], []) if item["kind"] != "remote" else []
        scopes = [dev.scope(r.get("laddr")) for r in here] or [dev.scope(item.get("bind") or "127.0.0.1")]
        found[key].append({**item, "via": via, "active": bool(here) or item["kind"] == "remote",
                           "scope": dev.SCOPE_ALL if dev.SCOPE_ALL in scopes else dev.SCOPE_LAN if dev.SCOPE_LAN in scopes
                           else dev.SCOPE_LOCAL, "owner": here[0].get("process_name") if here else None,
                           "users": users.get(item["listen"], 0) if item["kind"] != "remote" else None})

    for process in snapshot.get("processes", []):
        ssh = process.get("ssh")
        link = next((r for r in rows if r.get("pid") == process.get("pid") and r.get("raddr")
                     and dev.origin(r.get("raddr")) != "local"), None) if ssh else None
        if not link:
            continue
        key = (link["raddr"], link.get("rport"))
        alias = ssh.get("destination")
        aliases[key], by_alias[alias] = alias, key
        for item in ssh.get("forwards", []):
            add(key, item, "ssh")
        for item in host_settings(snapshot.get("ssh_config", []), alias)["forwards"]:
            add(key, item, "~/.ssh/config")
    for item in snapshot.get("vscode_forwards", []):
        key = by_alias.get(item.get("host"))
        # VS Code keeps a list of ports to restore: only those it really has open count
        if key and listening.get(item["listen"]):
            add(key, item, "VS Code" + (" (automático)" if item.get("auto") else ""))
    for items in found.values():
        items.sort(key=lambda f: (not f["active"], f["listen"]))
    return found, aliases


def model(history: list[dict], snapshot: dict, names: dict[str, str] | None = None) -> dict:
    names = names or {}
    rows = snapshot.get("connections", [])
    live = {(r.get("raddr"), r.get("rport")): r.get("pid") for r in rows
            if _client(r.get("process_name")) and r.get("raddr") and dev.origin(r.get("raddr")) != "local"}
    tunnels_by_session, aliases = forwards(snapshot)
    sessions: dict[tuple, dict] = {}
    inbound: dict[tuple, dict] = {}
    for row in history:
        remote, origin = row.get("remote_address"), dev.origin(row.get("remote_address"))
        if origin in (None, "local"):
            continue
        tunnels = {t for value in str(row.get("tunnel_types") or "").split(",") for t in [value.strip()] if t}
        if row.get("direction") == "inbound":
            entry = inbound.setdefault((remote, row.get("local_port")), {
                "remote": remote, "name": names.get(remote), "origin": origin, "port": row.get("local_port"),
                "first_seen": row["first_seen"], "last_seen": row["last_seen"]})
            entry["last_seen"] = max(entry["last_seen"], row["last_seen"])
            continue
        key = (remote, row.get("remote_port"))
        entry = sessions.setdefault(key, {"remote": remote, "port": row.get("remote_port"), "name": names.get(remote),
                                          "origin": origin, "process": row.get("process_name"), "tunnels": set(),
                                          "agent_forwarding": False, "first_seen": row["first_seen"],
                                          "last_seen": row["last_seen"]})
        entry["tunnels"] |= tunnels
        entry["agent_forwarding"] |= bool(row.get("agent_forwarding"))
        entry["first_seen"] = min(entry["first_seen"], row["first_seen"])
        entry["last_seen"] = max(entry["last_seen"], row["last_seen"])
    for key, pid in live.items():  # a session opened after the last collection is still shown
        sessions.setdefault(key, {"remote": key[0], "port": key[1], "name": names.get(key[0]), "origin": dev.origin(key[0]),
                                  "process": "ssh.exe", "tunnels": set(), "agent_forwarding": False,
                                  "first_seen": None, "last_seen": snapshot.get("taken_at")})
    for key, entry in sessions.items():
        entry["live"] = key in live
        entry["alias"] = aliases.get(key)
        entry["forwards"] = tunnels_by_session.get(key, []) if key in live else []
        entry["tunnels"] = sorted(entry["tunnels"] | {
            {"local": "local", "remote": "reverse", "dynamic": "socks"}[f["kind"]] for f in entry["forwards"]})
        entry["risks"] = _risks(entry)
    recent_first = sorted(sessions.values(), key=lambda e: str(e["last_seen"] or ""), reverse=True)
    ordered = sorted(recent_first, key=lambda e: not e["live"])  # live sessions first, each group newest first
    return {"sessions": ordered, "inbound": sorted(inbound.values(), key=lambda e: e["last_seen"], reverse=True)}


def _risks(session: dict) -> list[dict]:
    found = []
    if "reverse" in session["tunnels"]:
        found.append({"severity": "high", "text": ("El servidor remoto abre un puerto que llega hasta este equipo (-R).",
                                                   "The remote server opens a port that reaches this computer (-R).")})
    if session["agent_forwarding"]:
        found.append({"severity": "medium", "text": ("Reenvío del agente (-A): quien controle el servidor puede usar sus "
                                                     "claves mientras dure la sesión.", "Agent forwarding (-A): whoever "
                                                     "controls the server can use your keys during the session.")})
    for item in session.get("forwards", []):
        if item["kind"] != "remote" and item["active"] and item["scope"] != dev.SCOPE_LOCAL:
            found.append({"severity": "high", "text": (f"El túnel :{item['listen']} escucha en la red: otros equipos "
                                                       "pueden usarlo para llegar al servidor.",
                                                       f"Tunnel :{item['listen']} listens on the network: other "
                                                       "computers can use it to reach the server.")})
    return found


def tunnel_node_id(session: dict, item: dict) -> str:
    return f"t:{session['remote']}:{session['port']}:{item['kind']}:{item['listen']}"


def forward_for_port(snapshot: dict, port: int) -> tuple[str | None, dict] | None:
    """The tunnel behind a local port, with the SSH host alias it leads to (for "who uses the port?")."""
    found, aliases = forwards(snapshot)
    for key, items in found.items():
        for item in items:
            if item["kind"] != "remote" and item["listen"] == port and item["active"]:
                return aliases.get(key) or f"{key[0]}:{key[1]}", item
    return None


def worst(session: dict) -> str | None:
    levels = [risk["severity"] for risk in session.get("risks", [])]
    return "high" if "high" in levels else "medium" if levels else None


def graph(data: dict, lang: str = "es") -> dict:
    """PC in the centre; SSH servers on a ring; tunnel ports between PC and their server; inbound clients below."""
    en = lang == "en"
    nodes = [{"id": "host", "kind": "host", "label": "PC", "tip": "This computer" if en else "Este equipo",
              "x": 0, "y": 0, "r": 24, "color": "#64748b"}]
    edges = []
    sessions, inbound = data["sessions"], data["inbound"]
    total = max(len(sessions) + len(inbound), 1)
    most_tunnels = max((sum(f["active"] for f in s.get("forwards", [])) for s in sessions), default=0)
    radius = max(150, total * 22, most_tunnels * 24)  # room for a row of tunnels between PC and server
    for index, session in enumerate(sessions + inbound):
        angle = 2 * math.pi * index / total - math.pi / 2
        x, y = round(radius * math.cos(angle), 1), round(radius * math.sin(angle), 1)
        if session in inbound:
            node_id = f"i:{session['remote']}:{session['port']}"
            nodes.append({"id": node_id, "kind": "client", "label": session["name"] or session["remote"],
                          "sub": ("→ your SSH :" if en else "→ su SSH :") + str(session["port"]),
                          "color": ORIGIN_COLORS.get(session["origin"], "#94a3b8"), "x": x, "y": y, "r": 11})
            edges.append({"from": node_id, "to": "host", "color": ORIGIN_COLORS.get(session["origin"], "#94a3b8"),
                          "width": 2, "dashed": True})
            continue
        node_id = f"s:{session['remote']}:{session['port']}"
        nodes.append({"id": node_id, "kind": "server", "label": session.get("alias") or session["name"] or session["remote"],
                      "sub": f":{session['port']}" + (" · " + ",".join(session["tunnels"]) if session["tunnels"] else ""),
                      "tip": session["remote"], "color": ORIGIN_COLORS.get(session["origin"], "#94a3b8"),
                      "ring": RISK_COLORS.get(worst(session) or "", "#22c55e" if session["live"] else None),
                      "x": x, "y": y, "r": 15})
        edges.append({"from": "host", "to": node_id, "color": "#22c55e" if session["live"] else "#94a3b8",
                      "width": 3 if session["live"] else 1.5, "dashed": not session["live"]})
        active = [item for item in session.get("forwards", []) if item["active"]]
        # A row across the PC-server line, half way, evenly spaced however many tunnels there are
        across = (-math.sin(angle), math.cos(angle))
        middle = (radius * 0.5 * math.cos(angle), radius * 0.5 * math.sin(angle))
        for offset, item in enumerate(active):
            tunnel_id = tunnel_node_id(session, item)
            shift = 62 * (offset - (len(active) - 1) / 2)
            host, _, port = str(item["target"] or "").rpartition(":")
            target = ("SOCKS" if item["kind"] == "dynamic" else
                      (f"server :{item['listen']}" if en else f"servidor :{item['listen']}") if item["kind"] == "remote"
                      else f"→ :{port}" if host in {"localhost", "127.0.0.1", "::1"} else f"→ {item['target']}")
            nodes.append({"id": tunnel_id, "kind": "client",
                          "label": f"↩ {item['target']}" if item["kind"] == "remote" else f":{item['listen']}",
                          "sub": target if item["kind"] != "remote" else target, "tip": item["via"],
                          "color": "#a855f7", "ring": "#ef4444" if item["kind"] != "remote" and item["scope"] != dev.SCOPE_LOCAL
                          or item["kind"] == "remote" else None,
                          "x": round(middle[0] + across[0] * shift, 1),
                          "y": round(middle[1] + across[1] * shift, 1), "r": 9})
            edges.append({"from": "host", "to": tunnel_id, "color": "#a855f7", "width": 1.5})
            edges.append({"from": tunnel_id, "to": node_id, "color": "#a855f7", "width": 2})
    return {"nodes": nodes, "edges": edges, "extent": radius + 70}
