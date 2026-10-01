from __future__ import annotations

import socket
from typing import Any

from domain.models import CollectionRequest, CollectionResult, NetworkConnection


def _address(value: Any) -> tuple[str | None, int | None]:
    if not value:
        return None, None
    if hasattr(value, "ip"):
        return str(value.ip), int(value.port)
    return str(value[0]), int(value[1])


class PsutilConnectionCollector:
    name = "psutil_connections"

    def collect(self, request: CollectionRequest) -> CollectionResult:
        try:
            import psutil
        except ImportError:
            return CollectionResult(self.name, "connections", (), "skipped", ("psutil no está instalado",))

        try:
            raw_connections = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, OSError) as exc:
            return CollectionResult(self.name, "connections", (), "skipped", (f"No se pudieron leer conexiones: {exc}",))

        listeners: set[tuple[int, str, int, int | None]] = set()
        for conn in raw_connections:
            laddr, lport = _address(conn.laddr)
            if conn.type == socket.SOCK_STREAM and conn.status == psutil.CONN_LISTEN and laddr and lport is not None:
                listeners.add((conn.family, laddr, lport, conn.pid))

        items: list[NetworkConnection] = []
        warning_counts: dict[str, int] = {}
        process_cache: dict[int, tuple[str | None, str | None, str | None]] = {}
        for conn in raw_connections:
            laddr, lport = _address(conn.laddr)
            raddr, rport = _address(conn.raddr)
            proto = "tcp" if conn.type == socket.SOCK_STREAM else "udp" if conn.type == socket.SOCK_DGRAM else None
            if conn.status == psutil.CONN_LISTEN:
                direction = "listen"
            elif proto == "tcp" and conn.status == psutil.CONN_ESTABLISHED and laddr and lport is not None:
                candidates = ((conn.family, laddr, lport, conn.pid), (conn.family, "0.0.0.0", lport, conn.pid),
                              (conn.family, "::", lport, conn.pid))
                direction = "inbound" if any(candidate in listeners for candidate in candidates) else "outbound"
            elif proto == "tcp" and raddr:
                direction = "outbound"
            else:
                direction = None

            process_name = process_path = process_user = None
            if conn.pid is not None:
                if conn.pid not in process_cache:
                    try:
                        process = psutil.Process(conn.pid)
                        process_cache[conn.pid] = (process.name(), process.exe() or None, process.username())
                    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
                        process_cache[conn.pid] = (None, None, None)
                        key = type(exc).__name__
                        warning_counts[key] = warning_counts.get(key, 0) + 1
                process_name, process_path, process_user = process_cache[conn.pid]

            items.append(NetworkConnection(
                ts=request.now, source="psutil", proto=proto, direction=direction,
                laddr=laddr, lport=lport, raddr=raddr, rport=rport,
                state=conn.status or None, pid=conn.pid, process_name=process_name,
                process_path=process_path, process_user=process_user,
            ))
        warnings = tuple(
            f"No se pudieron consultar metadatos de {count} procesos: {kind}"
            for kind, count in sorted(warning_counts.items())
        )
        return CollectionResult(self.name, "connections", tuple(items), "ok", warnings)
