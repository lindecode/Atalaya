# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Docker containers as Atalaya sees them: published ports and their reach, risky settings, problems (pure functions).

Input is `docker inspect` / `docker ps` / `docker events` JSON. Environment values never leave this module: only the
names of variables that look like secrets are kept.
"""
from __future__ import annotations

import re
from collections import defaultdict

from domain import dev

# Ports whose service should not face the network: databases, queues, search engines, admin consoles
SENSITIVE_PORTS = {
    5432: "PostgreSQL", 3306: "MySQL/MariaDB", 1433: "SQL Server", 1521: "Oracle", 27017: "MongoDB",
    6379: "Redis", 11211: "Memcached", 9200: "Elasticsearch", 9300: "Elasticsearch", 5601: "Kibana",
    5672: "RabbitMQ", 15672: "RabbitMQ (admin)", 9092: "Kafka", 2181: "ZooKeeper", 8086: "InfluxDB",
    5984: "CouchDB", 7474: "Neo4j", 9000: "MinIO/Portainer", 9443: "Portainer",
    2375: "Docker API", 2376: "Docker API (TLS)", 8500: "Consul", 8200: "Vault",
}
DANGEROUS_CAPS = {"SYS_ADMIN", "NET_ADMIN", "SYS_PTRACE", "SYS_MODULE", "DAC_READ_SEARCH", "ALL"}
HOST_ROOTS = {"/", "c:\\", "c:/", "/run/desktop/mnt/host/c", "/mnt/c", "/host_mnt/c", "/var/lib/docker"}
SECRET_ENV = re.compile(r"(?i)(pass(word|wd)?|secret|token|api[_-]?key|private[_-]?key|credential|auth)")
RESTART_LOOP = 3          # restarts or deaths…
RESTART_WINDOW = 600      # …within ten minutes


def published(inspect: dict) -> list[dict]:
    """Every host binding of a container: container port, host address, host port and how far it reaches."""
    ports = (inspect.get("NetworkSettings") or {}).get("Ports") or {}
    result = []
    for spec, bindings in ports.items():
        container_port, _, proto = str(spec).partition("/")
        for binding in bindings or []:
            host_ip = binding.get("HostIp") or "0.0.0.0"  # empty means every interface
            host_port = int(binding["HostPort"]) if str(binding.get("HostPort") or "").isdigit() else None
            result.append({"container_port": int(container_port), "proto": proto or "tcp", "host_ip": host_ip,
                           "host_port": host_port, "scope": dev.scope(host_ip),
                           "service": SENSITIVE_PORTS.get(int(container_port))})
    # 0.0.0.0 and :: of the same port are one publication
    unique = {(p["host_port"], p["container_port"], p["proto"]): p for p in sorted(result, key=lambda p: p["host_ip"] == "0.0.0.0")}  # 0.0.0.0 wins
    return sorted(unique.values(), key=lambda p: (p["host_port"] or 0))


def secret_env_names(inspect: dict) -> list[str]:
    names = []
    for entry in (inspect.get("Config") or {}).get("Env") or []:
        name, _, value = str(entry).partition("=")
        if value and SECRET_ENV.search(name) and not name.endswith("_FILE"):  # *_FILE points to a secret file: good
            names.append(name)
    return sorted(set(names))


def mounts(inspect: dict) -> list[dict]:
    return [{"type": m.get("Type"), "name": m.get("Name"), "source": m.get("Source"), "destination": m.get("Destination"),
             "rw": bool(m.get("RW"))} for m in inspect.get("Mounts") or []]


def risks(inspect: dict) -> list[dict]:
    """Settings that widen what the container (or whoever reaches it) can do; each with a fix."""
    host = inspect.get("HostConfig") or {}
    found = []
    for port in published(inspect):
        if port["scope"] != dev.SCOPE_LOCAL:
            found.append({"kind": "published", "severity": "high" if port["service"] else "medium",
                          "detail": f"{port['host_ip']}:{port['host_port']}->{port['container_port']}/{port['proto']}"
                                    + (f" ({port['service']})" if port["service"] else ""),
                          "fix": f"-p 127.0.0.1:{port['host_port']}:{port['container_port']}"})
    if host.get("Privileged"):
        found.append({"kind": "privileged", "severity": "high", "detail": "--privileged",
                      "fix": "Quite --privileged y añada solo las capacidades necesarias"})
    caps = sorted({str(cap).upper().removeprefix("CAP_") for cap in host.get("CapAdd") or []} & DANGEROUS_CAPS)
    if caps:
        found.append({"kind": "capabilities", "severity": "high", "detail": "--cap-add " + ",".join(caps),
                      "fix": "Revise si de verdad necesita esas capacidades"})
    if str(host.get("NetworkMode") or "") == "host":
        found.append({"kind": "host_network", "severity": "medium", "detail": "--network host",
                      "fix": "Use una red bridge y publique solo los puertos necesarios"})
    for mount in mounts(inspect):
        source = str(mount["source"] or "").replace("\\", "/").rstrip("/").casefold() or "/"
        if source.endswith("docker.sock") or source.endswith("docker_engine"):
            found.append({"kind": "docker_socket", "severity": "high", "detail": f"{mount['source']} → {mount['destination']}",
                          "fix": "Montar el socket de Docker da control total del equipo; evítelo o use un proxy de solo lectura"})
        elif mount["type"] == "bind" and (source in {r.rstrip("/").casefold() or "/" for r in HOST_ROOTS}):
            found.append({"kind": "host_root", "severity": "high", "detail": f"{mount['source']} → {mount['destination']}"
                          + ("" if mount["rw"] else " (solo lectura)"), "fix": "Monte solo la carpeta del proyecto"})
    secrets = secret_env_names(inspect)
    if secrets:
        found.append({"kind": "env_secrets", "severity": "medium", "detail": ", ".join(secrets),
                      "fix": "Use secretos de Docker/Compose o variables *_FILE en lugar de valores en claro"})
    return found


def container(inspect: dict, stats: dict | None = None) -> dict:
    """Compact, secret-free model of one container for storage, rules, the page and the chat."""
    config, state = inspect.get("Config") or {}, inspect.get("State") or {}
    labels = config.get("Labels") or {}
    networks = ((inspect.get("NetworkSettings") or {}).get("Networks") or {})
    return {
        "id": str(inspect.get("Id") or "")[:12], "name": str(inspect.get("Name") or "").lstrip("/"),
        "image": config.get("Image"), "project": labels.get("com.docker.compose.project"),
        "service": labels.get("com.docker.compose.service"), "state": state.get("Status"),
        "health": (state.get("Health") or {}).get("Status"), "restart_count": inspect.get("RestartCount") or 0,
        "oom_killed": bool(state.get("OOMKilled")), "exit_code": state.get("ExitCode"),
        "started": state.get("StartedAt"), "user": config.get("User") or "root",
        "restart_policy": ((inspect.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name"),
        "published": published(inspect), "networks": [{"name": name, "ip": (net or {}).get("IPAddress") or None}
                                                     for name, net in networks.items()],
        "mounts": mounts(inspect), "risks": risks(inspect),
        "cpu": (stats or {}).get("CPUPerc"), "memory": (stats or {}).get("MemUsage"),
    }


def problems(events: list[dict]) -> list[dict]:
    """Container trouble in `docker events` JSON: OOM kills, unhealthy checks and restart loops (one per container)."""
    found, deaths = [], defaultdict(list)
    for event in sorted(events, key=lambda e: e.get("time") or 0):
        action = str(event.get("Action") or event.get("status") or "")
        attributes = (event.get("Actor") or {}).get("Attributes") or {}
        name = attributes.get("name") or str(event.get("id") or "")[:12]
        base = {"container": name, "image": attributes.get("image") or event.get("from"), "time": event.get("time")}
        if action == "oom":
            found.append({**base, "problem": "oom", "detail": "sin memoria (OOM)"})
        elif action.startswith("health_status") and action.endswith("unhealthy"):
            found.append({**base, "problem": "unhealthy", "detail": "health check fallido"})
        elif action in {"die", "restart"}:
            times = deaths[name]
            times.append(event.get("time") or 0)
            recent = [t for t in times if times[-1] - t <= RESTART_WINDOW]
            if len(recent) == RESTART_LOOP:  # report once when the loop is detected, not on every later restart
                found.append({**base, "problem": "restart_loop",
                              "detail": f"{len(recent)} reinicios en {RESTART_WINDOW // 60} min"
                                        + (f", código {attributes.get('exitCode')}" if attributes.get("exitCode") else "")})
    return found


def port_names(containers: list[dict]) -> dict[int, str]:
    """Host port -> 'container (image)', to name what com.docker.backend / wslrelay listens on for."""
    return {port["host_port"]: f"{c['name']} ({c['image']})" for c in containers for port in c["published"]
            if port["host_port"]}
