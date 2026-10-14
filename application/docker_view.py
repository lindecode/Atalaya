"""Docker tab model: containers by project, networks (with a node map), volumes, bind mounts and images (pure)."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timezone

from domain import dev

STATE_COLORS = {"running": "#22c55e", "exited": "#94a3b8", "created": "#94a3b8", "paused": "#f59e0b",
                "restarting": "#f97316", "dead": "#ef4444", "unhealthy": "#ef4444"}
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
ANONYMOUS = re.compile(r"^[0-9a-f]{64}$")


def state_of(container: dict) -> str:
    return "unhealthy" if container.get("health") == "unhealthy" else str(container.get("state") or "?")


def worst_risk(container: dict) -> str | None:
    levels = [risk["severity"] for risk in container.get("risks", [])]
    return max(levels, key=SEVERITY_RANK.get) if levels else None


def by_project(containers: list[dict]) -> list[tuple[str | None, list[dict]]]:
    """Compose projects first (alphabetically), loose containers last; running before stopped inside each."""
    groups = defaultdict(list)
    for container in containers:
        groups[container.get("project")].append(container)
    order = sorted((name for name in groups if name), key=str.casefold) + ([None] if None in groups else [])
    return [(name, sorted(groups[name], key=lambda c: (c.get("state") != "running", c["name"]))) for name in order]


def summary(inventory: dict) -> dict:
    containers = inventory.get("containers", [])
    return {
        "running": sum(c.get("state") == "running" for c in containers), "total": len(containers),
        "exposed": sum(p["scope"] != dev.SCOPE_LOCAL for c in containers for p in c.get("published", [])),
        "at_risk": sum(bool(c.get("risks")) for c in containers),
        "unhealthy": sum(c.get("health") == "unhealthy" or c.get("oom_killed") for c in containers),
        "dangling_images": sum(image_row(i, containers)["dangling"] for i in inventory.get("images", [])),
        "unused_volumes": sum(not row["used_by"] for row in volume_rows(inventory)),
    }


def _created(text: str | None) -> str | None:
    """'2026-09-01 10:00:00 +0000 UTC' (docker image ls) -> ISO."""
    if not text:
        return None
    try:
        return datetime.strptime(" ".join(str(text).split()[:3]), "%Y-%m-%d %H:%M:%S %z").isoformat()
    except ValueError:
        return None


def image_row(image: dict, containers: list[dict]) -> dict:
    repository, tag = image.get("Repository") or "<none>", image.get("Tag") or "<none>"
    name = f"{repository}:{tag}"
    image_id = str(image.get("ID") or "").removeprefix("sha256:")[:12]
    users = [c["name"] for c in containers if c.get("image") in {name, repository if tag == "latest" else name}]
    created = _created(image.get("CreatedAt"))
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(created)).days if created else None
    return {"image": name, "id": image_id, "size": image.get("Size"), "created": created, "age_days": age,
            "containers": users, "dangling": repository == "<none>", "latest": tag == "latest"}


def image_rows(inventory: dict) -> list[dict]:
    containers = inventory.get("containers", [])
    rows = [image_row(image, containers) for image in inventory.get("images", [])]
    return sorted(rows, key=lambda row: (row["dangling"], not row["containers"], row["image"]))


def network_rows(inventory: dict) -> list[dict]:
    rows = []
    for network in inventory.get("networks", []):
        config = ((network.get("IPAM") or {}).get("Config") or [{}])
        members = [{"name": member.get("Name"), "ip": str(member.get("IPv4Address") or "").split("/")[0] or None}
                   for member in (network.get("Containers") or {}).values()]
        rows.append({"name": network.get("Name"), "driver": network.get("Driver"), "scope": network.get("Scope"),
                     "internal": bool(network.get("Internal")), "subnet": (config[0] or {}).get("Subnet") if config else None,
                     "gateway": (config[0] or {}).get("Gateway") if config else None, "containers": members})
    return sorted(rows, key=lambda row: (not row["containers"], row["name"] or ""))


def volume_rows(inventory: dict) -> list[dict]:
    users = defaultdict(list)
    for container in inventory.get("containers", []):
        for mount in container.get("mounts", []):
            if mount.get("type") == "volume" and mount.get("name"):
                users[mount["name"]].append(container["name"])
    rows = []
    for volume in inventory.get("volumes", []):
        labels = volume.get("Labels") or {}
        rows.append({"name": volume.get("Name"), "anonymous": bool(ANONYMOUS.match(str(volume.get("Name") or ""))),
                     "driver": volume.get("Driver"), "project": labels.get("com.docker.compose.project"),
                     "created": volume.get("CreatedAt"), "mountpoint": volume.get("Mountpoint"),
                     "used_by": users.get(volume.get("Name"), [])})
    return sorted(rows, key=lambda row: (not row["used_by"], row["anonymous"], row["name"] or ""))


def bind_mounts(inventory: dict) -> list[dict]:
    """Host folders mounted into containers; the sensitive ones are those R23 flags."""
    sensitive = {risk["detail"] for c in inventory.get("containers", []) for risk in c.get("risks", [])
                 if risk["kind"] in {"docker_socket", "host_root"}}
    rows = []
    for container in inventory.get("containers", []):
        for mount in container.get("mounts", []):
            if mount.get("type") == "bind":
                detail = f"{mount['source']} → {mount['destination']}"
                rows.append({"container": container["name"], "source": mount["source"], "destination": mount["destination"],
                             "rw": mount["rw"], "sensitive": any(detail in text for text in sensitive)})
    return rows


def network_graph(inventory: dict, lang: str = "es") -> dict:
    """Docker in the centre, networks on a ring, containers outside next to their (first) network."""
    networks = [row for row in network_rows(inventory) if row["containers"]]
    states = {c["name"]: c for c in inventory.get("containers", [])}
    nodes = [{"id": "host", "kind": "host", "label": "Docker", "tip": "Docker", "x": 0, "y": 0, "r": 26,
              "color": "#2496ed"}]
    edges, placed = [], {}
    count = max(len(networks), 1)
    inner = max(110, count * 30)
    outer = inner + 120
    for index, network in enumerate(networks):
        angle = 2 * math.pi * index / count - math.pi / 2
        network_id = f"n:{network['name']}"
        nodes.append({"id": network_id, "kind": "server", "label": network["name"], "sub": network.get("subnet") or network["driver"],
                      "color": "#64748b", "ring": "#2496ed", "r": 15,
                      "x": round(inner * math.cos(angle), 1), "y": round(inner * math.sin(angle), 1)})
        edges.append({"from": "host", "to": network_id, "color": "#2496ed", "width": 2})
        members = network["containers"]
        spread = min(math.pi / count * 0.8, 0.12 * len(members) + 0.2)  # tight fan, wider with more members
        for position, member in enumerate(members):
            container_id = f"c:{member['name']}"
            if container_id not in placed:
                offset = 0 if len(members) == 1 else -spread + 2 * spread * position / (len(members) - 1)
                container = states.get(member["name"], {})
                risk = worst_risk(container)
                placed[container_id] = True
                nodes.append({"id": container_id, "kind": "client", "label": member["name"], "sub": member.get("ip"),
                              "tip": container.get("image"), "color": STATE_COLORS.get(state_of(container), "#94a3b8"),
                              "ring": "#ef4444" if risk in {"high", "critical"} else "#f59e0b" if risk else None, "r": 11,
                              "x": round(outer * math.cos(angle + offset), 1), "y": round(outer * math.sin(angle + offset), 1)})
            edges.append({"from": network_id, "to": container_id, "color": "#94a3b8", "width": 1.5})
    has_containers = any(node["kind"] == "client" for node in nodes)
    return {"nodes": nodes, "edges": edges, "extent": (outer if has_containers else inner) + 60}


TOOL_ARGS = {"name", "only_risky"}


def tool_result(inventory: dict, args: dict) -> dict:
    """get_containers for the chat: compact containers (id = container name) plus totals and housekeeping."""
    unexpected = set(args) - TOOL_ARGS
    if unexpected:
        raise ValueError(f"Argumentos no permitidos: {sorted(unexpected)}")
    if not inventory.get("available"):
        return {"summary": {"docker": "no disponible", "reason": inventory.get("error")}, "rows": []}
    name = str(args.get("name") or "").casefold()
    rows = []
    for container in inventory.get("containers", []):
        if name and name not in container["name"].casefold() and name not in str(container.get("image") or "").casefold():
            continue
        if args.get("only_risky") and not container.get("risks"):
            continue
        rows.append({"id": container["name"], "image": container.get("image"), "project": container.get("project"),
                     "state": state_of(container), "restart_count": container.get("restart_count"),
                     "oom_killed": container.get("oom_killed"), "exit_code": container.get("exit_code"),
                     "published": [f"{p['host_ip']}:{p['host_port']}->{p['container_port']} ({p['scope']})"
                                   for p in container.get("published", [])],
                     "risks": [f"{r['kind']}: {r['detail']} → {r['fix']}" for r in container.get("risks", [])],
                     "networks": [n["name"] for n in container.get("networks", [])],
                     "cpu": container.get("cpu"), "memory": container.get("memory")})
    return {"summary": {**summary(inventory), "returned": len(rows[:25]),
                        "reach_legend": "local = solo este equipo, lan = red local, all = todas las redes"},
            "rows": rows[:25]}
