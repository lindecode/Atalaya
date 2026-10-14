"""Desarrollo page model: servers with their reach and clients, runtimes, and the node map (pure functions)."""
from __future__ import annotations

import math
from collections import defaultdict

from domain import dev

SCOPE_RANK = {dev.SCOPE_LOCAL: 0, dev.SCOPE_LAN: 1, dev.SCOPE_ALL: 2}
SCOPE_COLORS = {dev.SCOPE_LOCAL: "#22c55e", dev.SCOPE_LAN: "#f59e0b", dev.SCOPE_ALL: "#ef4444"}
ORIGIN_COLORS = {"local": "#94a3b8", "lan": "#3b82f6", "internet": "#ef4444"}


WINDOWS_SERVICES = {"?", "system", "svchost.exe", "lsass.exe", "wininit.exe", "services.exe", "spoolsv.exe"}


def _windows_service(entry: dict) -> bool:
    """Windows' own listeners (RPC 135 and the 49152+ range, SMB 445, NetBIOS 139): normal, not the developer's."""
    return str(entry["process"]).casefold() in WINDOWS_SERVICES


def servers(snapshot: dict, include_all: bool = False) -> list[dict]:
    """One entry per (port, process): widest reach over its addresses, runtime, debug label, clients now.

    By default only development servers and anything reachable beyond this computer; `include_all` adds the
    loopback-only helpers of ordinary programs (IDE plugins, vendor utilities…).
    """
    processes = {row["pid"]: row for row in snapshot.get("processes", [])}
    clients = defaultdict(list)
    for row in snapshot.get("connections", []):
        if row.get("direction") == "inbound" and row.get("raddr"):
            clients[row.get("lport")].append({"ip": row["raddr"], "port": row.get("rport"),
                                              "origin": dev.origin(row["raddr"])})
    result: dict[tuple, dict] = {}
    for row in snapshot.get("connections", []):
        if row.get("direction") != "listen" or row.get("lport") is None:
            continue
        key = (row["lport"], row.get("process_name") or "?")
        reach = dev.scope(row.get("laddr"))
        entry = result.get(key)
        if entry is None:
            process = processes.get(row.get("pid"), {})
            runtime = dev.runtime(row.get("process_name"), row.get("process_path"))
            entry = result[key] = {
                "id": f"s:{key[0]}:{key[1]}", "port": key[0], "process": key[1], "pid": row.get("pid"),
                "path": row.get("process_path"), "runtime": runtime.key, "language": runtime.label,
                "color": runtime.color, "scope": reach, "addresses": [], "debug": dev.debug_port(key[0]),
                "started": process.get("started"), "memory_mb": process.get("memory_mb"),
                "command": process.get("command"), "target": process.get("target"),
                "clients": clients.get(key[0], []),
            }
        if row.get("laddr") not in entry["addresses"]:
            entry["addresses"].append(row.get("laddr"))
        if SCOPE_RANK[reach] > SCOPE_RANK[entry["scope"]]:
            entry["scope"] = reach
    rows = [entry for entry in result.values()
            if include_all or entry["runtime"] in dev.DEV_RUNTIMES
            or (entry["scope"] != dev.SCOPE_LOCAL and not _windows_service(entry))]
    return sorted(rows, key=lambda entry: (-SCOPE_RANK[entry["scope"]], entry["runtime"], entry["port"]))


def runtimes(snapshot: dict) -> list[dict]:
    """Development processes grouped by language, with memory and the servers each one opened."""
    ports = defaultdict(list)
    for row in snapshot.get("connections", []):
        if row.get("direction") == "listen" and row.get("lport") not in ports[row.get("pid")]:
            ports[row.get("pid")].append(row.get("lport"))
    groups: dict[str, dict] = {}
    for process in snapshot.get("processes", []):
        runtime = dev.runtime(process.get("name"), process.get("path"))
        if runtime.key not in dev.DEV_RUNTIMES:
            continue
        group = groups.setdefault(runtime.key, {"key": runtime.key, "language": runtime.label, "color": runtime.color,
                                                "processes": [], "memory_mb": 0})
        group["processes"].append({**process, "ports": sorted(p for p in ports.get(process["pid"], []) if p is not None)})
        group["memory_mb"] += process.get("memory_mb") or 0
    return sorted(groups.values(), key=lambda group: -group["memory_mb"])


def _short(text: str, limit: int = 16) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def graph(server_rows: list[dict], history: list[dict] | None = None, lang: str = "es",
          include_local_clients: bool = False) -> dict:
    """Radial node map: this computer in the centre, servers on a ring, their clients outside.

    `history` holds earlier notices (kind 'client') so a client that already left still shows, dashed.
    """
    nodes = [{"id": "host", "kind": "host", "label": "PC", "tip": "This computer" if lang == "en" else "Este equipo",
              "x": 0, "y": 0, "r": 24, "color": "#64748b"}]
    edges = []
    count = max(len(server_rows), 1)
    inner = max(120, count * 14)   # enough circumference for each server's label
    outer = inner + 110
    placed: dict[str, dict] = {}
    by_port = {row["port"]: row for row in server_rows}
    for index, server in enumerate(server_rows):
        angle = 2 * math.pi * index / count - math.pi / 2
        server["_angle"] = angle
        nodes.append({"id": server["id"], "kind": "server", "label": f":{server['port']}",
                      "sub": _short(server.get("target") or server["process"].removesuffix(".exe")),
                      "tip": server["process"], "color": server["color"],
                      "ring": SCOPE_COLORS[server["scope"]], "x": round(inner * math.cos(angle), 1),
                      "y": round(inner * math.sin(angle), 1), "r": 17 if server.get("debug") else 14})
        edges.append({"from": "host", "to": server["id"], "color": SCOPE_COLORS[server["scope"]], "width": 2})
    links: dict[tuple, dict] = {}
    for server in server_rows:
        for client in server["clients"]:
            if client["origin"] in (None, "local") and not include_local_clients:
                continue
            link = links.setdefault((client["ip"], server["id"]), {"live": True, "count": 0, "origin": client["origin"]})
            link["count"] += 1
    for notice in history or []:
        server = by_port.get(notice.get("lport"))
        if notice.get("kind") == "client" and server and notice.get("remote_ip"):
            links.setdefault((notice["remote_ip"], server["id"]),
                             {"live": False, "count": 1, "origin": notice.get("network")})
    spread = math.pi / count * 0.8
    per_server = defaultdict(list)
    for (ip, server_id), _ in links.items():
        if ip not in placed:
            placed[ip] = {}
            per_server[server_id].append(ip)
    angles = {row["id"]: row["_angle"] for row in server_rows}
    for server_id, ips in per_server.items():
        for index, ip in enumerate(ips):
            offset = 0 if len(ips) == 1 else -spread + 2 * spread * index / (len(ips) - 1)
            angle = angles[server_id] + offset
            origin = next(link["origin"] for (other, sid), link in links.items() if other == ip)
            nodes.append({"id": f"c:{ip}", "kind": "client", "label": ip, "color": ORIGIN_COLORS.get(origin or "", "#94a3b8"),
                          "x": round(outer * math.cos(angle), 1), "y": round(outer * math.sin(angle), 1), "r": 9})
    for (ip, server_id), link in links.items():
        edges.append({"from": f"c:{ip}", "to": server_id, "color": ORIGIN_COLORS.get(link["origin"] or "", "#94a3b8"),
                      "width": min(1 + link["count"], 5), "dashed": not link["live"]})
    for server in server_rows:
        server.pop("_angle", None)
    has_clients = any(node["kind"] == "client" for node in nodes)
    return {"nodes": nodes, "edges": edges, "extent": (outer if has_clients else inner) + 55}
