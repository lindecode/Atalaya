"""SSH map model: the servers this computer connects to, the tunnels it opens, and who connects to its own SSH (pure).

History comes from ssh_observations (the collector keeps only flags such as -L/-R/-D/-A, never destinations from the
command line); "connected now" and the tunnel listeners come from the live sockets.
"""
from __future__ import annotations

import math
from collections import defaultdict

from domain import dev

SSH_CLIENTS = {"ssh.exe", "scp.exe", "sftp.exe", "ssh", "scp", "sftp"}
TUNNEL_LABELS = {"local": ("Túnel local (-L)", "Local tunnel (-L)"), "reverse": ("Túnel inverso (-R)", "Reverse tunnel (-R)"),
                 "socks": ("Proxy SOCKS (-D)", "SOCKS proxy (-D)")}
ORIGIN_COLORS = {"lan": "#3b82f6", "internet": "#ef4444", "local": "#94a3b8"}
RISK_COLORS = {"high": "#ef4444", "medium": "#f59e0b"}


def _client(name) -> bool:
    return str(name or "").casefold() in SSH_CLIENTS


def model(history: list[dict], snapshot: dict, names: dict[str, str] | None = None) -> dict:
    names = names or {}
    rows = snapshot.get("connections", [])
    live = {(r.get("raddr"), r.get("rport")): r.get("pid") for r in rows
            if _client(r.get("process_name")) and r.get("raddr") and dev.origin(r.get("raddr")) != "local"}
    listeners = defaultdict(list)  # pid -> tunnel ports opened on this computer by that ssh process
    for r in rows:
        if _client(r.get("process_name")) and r.get("direction") == "listen":
            users = sum(o.get("direction") == "inbound" and o.get("lport") == r.get("lport") for o in rows)
            if all(item["port"] != r.get("lport") for item in listeners[r.get("pid")]):
                listeners[r.get("pid")].append({"port": r.get("lport"), "address": r.get("laddr"),
                                                "scope": dev.scope(r.get("laddr")), "users": users})
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
        entry["listeners"] = listeners.get(live.get(key), []) if key in live else []
        entry["tunnels"] = sorted(entry["tunnels"])
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
    for listener in session.get("listeners", []):
        if listener["scope"] != dev.SCOPE_LOCAL:
            found.append({"severity": "high", "text": (f"El túnel :{listener['port']} escucha en la red: otros equipos "
                                                       "pueden usarlo para llegar al servidor.",
                                                       f"Tunnel :{listener['port']} listens on the network: other "
                                                       "computers can use it to reach the server.")})
    return found


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
    radius = max(150, total * 22)
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
        nodes.append({"id": node_id, "kind": "server", "label": session["name"] or session["remote"],
                      "sub": f":{session['port']}" + (" · " + ",".join(session["tunnels"]) if session["tunnels"] else ""),
                      "tip": session["remote"], "color": ORIGIN_COLORS.get(session["origin"], "#94a3b8"),
                      "ring": RISK_COLORS.get(worst(session) or "", "#22c55e" if session["live"] else None),
                      "x": x, "y": y, "r": 15})
        edges.append({"from": "host", "to": node_id, "color": "#22c55e" if session["live"] else "#94a3b8",
                      "width": 3 if session["live"] else 1.5, "dashed": not session["live"]})
        for offset, listener in enumerate(session["listeners"]):
            tunnel_id = f"t:{listener['port']}"
            spread = 0.18 * (offset - (len(session["listeners"]) - 1) / 2)
            nodes.append({"id": tunnel_id, "kind": "client", "label": f":{listener['port']}",
                          "sub": (f"{listener['users']} apps" if en else f"{listener['users']} apps"),
                          "color": "#a855f7", "ring": "#ef4444" if listener["scope"] != dev.SCOPE_LOCAL else None,
                          "x": round(radius * 0.5 * math.cos(angle + spread + 0.35), 1),
                          "y": round(radius * 0.5 * math.sin(angle + spread + 0.35), 1), "r": 9})
            edges.append({"from": "host", "to": tunnel_id, "color": "#a855f7", "width": 1.5})
            edges.append({"from": tunnel_id, "to": node_id, "color": "#a855f7", "width": 2})
    return {"nodes": nodes, "edges": edges, "extent": radius + 70}
