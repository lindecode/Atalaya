"""Desarrollo page model: servers with their reach and clients, runtimes, and the node map (pure functions)."""
from __future__ import annotations

import math
from collections import defaultdict

from domain import dev

SCOPE_RANK = {dev.SCOPE_LOCAL: 0, dev.SCOPE_LAN: 1, dev.SCOPE_ALL: 2}
SCOPE_COLORS = {dev.SCOPE_LOCAL: "#22c55e", dev.SCOPE_LAN: "#f59e0b", dev.SCOPE_ALL: "#ef4444"}
ORIGIN_COLORS = {"local": "#94a3b8", "lan": "#3b82f6", "internet": "#ef4444"}


def _windows_service(entry: dict) -> bool:
    return dev.windows_service(entry["process"])


def servers(snapshot: dict, include_all: bool = False, port_names: dict[int, str] | None = None) -> list[dict]:
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
                "command": process.get("command"),
                # Docker Desktop listens for its containers: name the container, not com.docker.backend
                "target": (port_names or {}).get(key[0]) if runtime.key == "container" and (port_names or {}).get(key[0])
                else process.get("target"),
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


def timeline(history: dict, include_all: bool = False) -> list[dict]:
    """When each server was up: runs of consecutive collections that saw it listening.

    A collection without it means it was down; a gap much longer than the usual interval (computer off or
    asleep) also ends the run instead of drawing it as up all night.
    """
    from datetime import datetime, timedelta

    snapshots = [datetime.fromisoformat(ts) for ts in history.get("snapshots", [])]
    if not snapshots:
        return []
    index = {ts: position for position, ts in enumerate(history["snapshots"])}
    deltas = sorted((b - a).total_seconds() for a, b in zip(snapshots, snapshots[1:])) or [300.0]
    usual = max(deltas[len(deltas) // 2], 60.0)
    seen: dict[tuple, dict] = {}
    for row in history.get("rows", []):
        key = (row["lport"], row.get("process_name") or "?")
        entry = seen.setdefault(key, {"positions": set(), "scope": dev.SCOPE_LOCAL, "path": row.get("process_path")})
        entry["positions"].add(index[row["ts"]])
        reach = dev.scope(row.get("laddr"))
        if SCOPE_RANK[reach] > SCOPE_RANK[entry["scope"]]:
            entry["scope"] = reach
    segments = []
    for (port, process), entry in seen.items():
        runtime = dev.runtime(process, entry["path"])
        candidate = {"process": process, "runtime": runtime.key, "scope": entry["scope"]}
        if not include_all and not (runtime.key in dev.DEV_RUNTIMES or (
                entry["scope"] != dev.SCOPE_LOCAL and not _windows_service(candidate))):
            continue
        positions = sorted(entry["positions"])
        start = previous = positions[0]
        for position in positions[1:] + [None]:
            continuous = (position == previous + 1 and
                          (snapshots[position] - snapshots[previous]).total_seconds() <= 3 * usual) if position is not None else False
            if continuous:
                previous = position
                continue
            end = snapshots[previous] if previous > start else snapshots[start] + timedelta(seconds=usual)
            segments.append({"server": f":{port} · {process.removesuffix('.exe')}", "port": port, "process": process,
                             "language": runtime.label, "color": runtime.color, "scope": entry["scope"],
                             "start": snapshots[start].isoformat(), "end": end.isoformat()})
            if position is not None:
                start = previous = position
    return sorted(segments, key=lambda segment: (segment["port"], segment["start"]))


TOOL_ARGS = {"port", "process", "include_all"}


def tool_result(snapshot: dict, notices: list[dict], args: dict) -> dict:
    """get_dev_servers for the chat: compact rows (id = port) plus totals, with past clients from the notices."""
    unexpected = set(args) - TOOL_ARGS
    if unexpected:
        raise ValueError(f"Argumentos no permitidos: {sorted(unexpected)}")
    port = int(args["port"]) if args.get("port") not in (None, "") else None
    process = str(args.get("process") or "").casefold().removesuffix(".exe")
    rows = servers(snapshot, include_all=bool(args.get("include_all")) or port is not None)
    rows = [row for row in rows if (port is None or row["port"] == port)
            and (not process or process in row["process"].casefold() or process in row["language"].casefold())]
    result = []
    for row in rows[:25]:
        past = [{"ip": n.get("remote_ip"), "network": n.get("network"), "ts": n.get("ts")} for n in notices
                if n.get("kind") == "client" and n.get("lport") == row["port"]][:10]
        result.append({
            "id": row["port"], "port": row["port"], "process": row["process"], "language": row["language"],
            "reach": row["scope"], "addresses": row["addresses"], "debug_port": row["debug"],
            "application": row.get("target"), "started": row.get("started"), "memory_mb": row.get("memory_mb"),
            "clients_now": [f"{c['ip']} ({c['origin']})" for c in row["clients"] if c["origin"] != "local"][:10],
            "local_clients_now": sum(c["origin"] == "local" for c in row["clients"]),
            "recent_external_clients": past,
        })
    summary = {"servers": len(rows), "returned": len(result),
               "exposed": sum(row["scope"] != dev.SCOPE_LOCAL for row in rows),
               "debug_exposed": sum(bool(row["debug"]) and row["scope"] != dev.SCOPE_LOCAL for row in rows),
               "external_clients_now": sum(c["origin"] in {"lan", "internet"} for row in rows for c in row["clients"]),
               "reach_legend": "local = solo este equipo, lan = red local, all = todas las redes (0.0.0.0/::)"}
    return {"summary": summary, "rows": result}


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
    spread = min(math.pi / count * 0.8, 0.9)  # a lone server must not fan its clients around the whole ring
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


# How to bind each kind of server to this computer only (shown as a hint, never run)
LOCAL_BIND_HINTS = {
    "java": "server.address=127.0.0.1 (Spring) o -Dserver.address=127.0.0.1",
    "node": "--host 127.0.0.1 (Vite/Next) o HOST=127.0.0.1",
    "python": "--host 127.0.0.1 (uvicorn/Flask) o --bind 127.0.0.1 (gunicorn)",
    "dotnet": "--urls http://127.0.0.1:PUERTO",
    "db": "listen_addresses='localhost' (PostgreSQL) o bind-address=127.0.0.1 (MySQL)",
    "ruby": "-b 127.0.0.1", "php": "php -S 127.0.0.1:PUERTO",
}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def recommendations(server_rows: list[dict], docker_data: dict | None = None, ssh_data: dict | None = None) -> list[dict]:
    """What to fix first across servers, Docker and SSH: {severity, text: (es, en), fix}, most severe first."""
    found = []
    for row in server_rows:
        if row["scope"] == dev.SCOPE_LOCAL:
            continue
        where = f":{row['port']} ({row['process']})"
        if row.get("debug"):
            found.append({"severity": "high", "fix": "127.0.0.1",
                          "text": (f"{where}: {row['debug']} abierto a la red; quien lo alcance ejecuta código.",
                                   f"{where}: {row['debug']} open to the network; whoever reaches it runs code.")})
        elif row["runtime"] in dev.DEV_RUNTIMES and row["runtime"] != "container":
            found.append({"severity": "medium", "fix": LOCAL_BIND_HINTS.get(row["runtime"], "127.0.0.1"),
                          "text": (f"{where} escucha en todas las redes; si solo lo usa usted, haga que escuche en 127.0.0.1.",
                                   f"{where} listens on every network; if only you use it, bind it to 127.0.0.1.")})
        elif row["runtime"] != "container":
            found.append({"severity": "low", "fix": None,
                          "text": (f"{where} acepta conexiones de la red; si no lo necesita, bloquéelo en el firewall.",
                                   f"{where} accepts network connections; if you do not need that, block it in the firewall.")})
    for container in (docker_data or {}).get("containers", []) if (docker_data or {}).get("available") else []:
        for risk in container.get("risks", []):
            found.append({"severity": "high" if risk["severity"] in {"high", "critical"} else "medium",
                          "fix": risk["fix"] if risk["fix"].startswith("-p ") else None,
                          "text": (f"Docker {container['name']}: {risk['detail']}. {risk['fix'] if not risk['fix'].startswith('-p ') else ''}".strip(),
                                   f"Docker {container['name']}: {risk['detail']}.")})
    for session in (ssh_data or {}).get("sessions", []):
        for risk in session.get("risks", []):
            where = f"SSH {session.get('name') or session['remote']}:{session['port']}"
            found.append({"severity": risk["severity"], "fix": None,
                          "text": (f"{where}: {risk['text'][0]}", f"{where}: {risk['text'][1]}")})
    return sorted(found, key=lambda item: SEVERITY_ORDER.get(item["severity"], 3))
