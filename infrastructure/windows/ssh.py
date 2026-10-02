from __future__ import annotations

import hashlib
import os
import socket

from domain.models import CollectionRequest, CollectionResult, SSHObservation
from infrastructure.windows.connections import _address


SSH_PROCESSES = {"ssh.exe", "sshd.exe", "scp.exe", "sftp.exe", "ssh-agent.exe"}


def _safe_command(process_name: str, command: list[str]) -> tuple[str, str | None, bool]:
    """Retain behavior flags only. Destinations, commands, paths and values are intentionally discarded."""
    flags, tunnels, forwarding = [], [], False
    for value in command[1:]:
        if value == "-A": forwarding = True; flags.append("-A")
        elif value in {"-L", "-R", "-D"}:
            flags.append(value); tunnels.append({"-L": "local", "-R": "reverse", "-D": "socks"}[value])
        elif value.startswith(("-L", "-R", "-D")) and len(value) > 2:
            flag = value[:2]; flags.append(flag); tunnels.append({"-L": "local", "-R": "reverse", "-D": "socks"}[flag])
    return " ".join([process_name, *sorted(set(flags))]), ",".join(sorted(set(tunnels))) or None, forwarding


class SSHObservationCollector:
    name = "ssh_observability"

    def collect(self, request: CollectionRequest) -> CollectionResult:
        try:
            import psutil
        except ImportError:
            return CollectionResult(self.name, "ssh_observations", (), "skipped", ("psutil no está instalado",))
        items, warnings = [], []
        try:
            connections = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, OSError) as exc:
            return CollectionResult(self.name, "ssh_observations", (), "skipped", (f"No se pudieron leer conexiones SSH: {exc}",))
        cache = {}
        for connection in connections:
            local_address, local_port = _address(connection.laddr)
            remote_address, remote_port = _address(connection.raddr)
            metadata = (None, None, None, [], None)
            if connection.pid is not None:
                if connection.pid not in cache:
                    try:
                        process = psutil.Process(connection.pid)
                        cache[connection.pid] = (process.name().casefold(), process.exe() or None,
                                                 process.username(), process.cmdline(), process.name())
                    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                        cache[connection.pid] = metadata
                metadata = cache[connection.pid]
            normalized, path, user, command, display_name = metadata
            is_ssh = normalized in SSH_PROCESSES or local_port == 22 or remote_port == 22
            if not is_ssh: continue
            display_name = display_name or normalized
            summary, tunnels, forwarding = _safe_command(display_name or "unknown", command or [])
            if normalized == "sshd.exe" or local_port == 22:
                direction = "listen" if not remote_address else "inbound"
            else:
                direction = "outbound"
            identity = f"{request.now}|{connection.pid}|{local_address}|{local_port}|{remote_address}|{remote_port}|{connection.status}"
            items.append(SSHObservation(
                request.now, "session", direction, local_address, local_port, remote_address, remote_port,
                connection.status or None, connection.pid, display_name, path, user, summary, tunnels,
                forwarding, None, None, hashlib.sha256(identity.encode()).hexdigest(),
            ))
        if os.name == "nt":
            for service_name in ("sshd", "ssh-agent"):
                try:
                    service = psutil.win_service_get(service_name).as_dict()
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
                    warnings.append(f"No se pudo consultar {service_name}: {type(exc).__name__}")
                    continue
                identity = f"{request.now}|service|{service_name}|{service.get('status')}|{service.get('start_type')}"
                items.append(SSHObservation(
                    request.now, "service", None, None, None, None, None, None, service.get("pid"),
                    service_name, service.get("binpath"), None, None, None, None, service.get("status"),
                    service.get("start_type"), hashlib.sha256(identity.encode()).hexdigest(),
                ))
        return CollectionResult(self.name, "ssh_observations", tuple(items), "ok", tuple(warnings))
