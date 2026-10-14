"""Live network watch: who connects to this computer's servers, pings it or scans it, and new exposed servers.

The tray polls it every few seconds, so a notification arrives while it still matters, not at the next collection
cycle. Every notice is also stored for the Desarrollo page. Repeats are muted per (kind, address, port) for an hour.
"""
from __future__ import annotations

import ipaddress
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Iterable

from domain import dev

MUTE_SECONDS = 3600
SCAN_SECONDS = 120


@dataclass(frozen=True)
class Notice:
    ts: str
    kind: str            # client | ping | scan | exposed
    network: str | None  # lan | internet (None for 'exposed')
    remote_ip: str | None
    lport: int | None
    process_name: str | None
    detail: str

    def title(self, lang: str = "es") -> str:
        en = lang == "en"
        where = {"internet": "Internet", "lan": "local network" if en else "red local"}.get(self.network or "", "")
        return {
            "client": (f"Connection from {where}" if en else f"Conexión desde {where}"),
            "ping": (f"Ping from {where}" if en else f"Ping desde {where}"),
            "scan": (f"Port scan from {where}" if en else f"Escaneo de puertos desde {where}"),
            "exposed": ("New server exposed to the network" if en else "Nuevo servidor expuesto a la red"),
        }[self.kind]

    def message(self, lang: str = "es") -> str:
        en = lang == "en"
        process = self.process_name or "?"
        if self.kind == "client":
            return (f"{self.remote_ip} → port {self.lport} ({process})" if en
                    else f"{self.remote_ip} → puerto {self.lport} ({process})")
        if self.kind == "ping":
            return f"{self.remote_ip} " + ("checked whether this computer exists" if en else "comprobó si este equipo existe")
        if self.kind == "scan":
            return f"{self.remote_ip}: {self.detail}"
        return (f"{process} listens on port {self.lport} ({self.detail})" if en
                else f"{process} escucha en el puerto {self.lport} ({self.detail})")


def parse_trusted(text: str | None) -> tuple:
    """'192.168.1.50, 10.0.0.0/24' -> networks; invalid entries raise ValueError with the offending text."""
    networks = []
    for item in str(text or "").replace(";", ",").replace("\n", ",").split(","):
        item = item.strip()
        if item:
            try:
                networks.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                raise ValueError(f"IP o red no válida: {item}") from None
    return tuple(networks)


class NetworkWatcher:
    """`connections()` returns connection rows (direction, laddr, lport, raddr, process_name…), `firewall()` the
    firewall rows written since the last call, `local_addresses()` this computer's own IPs."""

    def __init__(self, connections: Callable[[], Iterable[dict]], firewall: Callable[[], Iterable[dict]],
                 local_addresses: Callable[[], set[str]], now_iso: Callable[[], str],
                 trusted: tuple = (), scan_ports: int = 20, monotonic: Callable[[], float] = time.monotonic):
        self.connections, self.firewall, self.local_addresses = connections, firewall, local_addresses
        self.now_iso, self.monotonic = now_iso, monotonic
        self.trusted, self.scan_ports = trusted, scan_ports
        self.muted: dict[tuple, float] = {}
        self.exposed: set[tuple] | None = None  # servers already listening when the watch started
        self.drops: dict[str, deque] = defaultdict(deque)

    def _trusted(self, address: str | None) -> bool:
        ip = dev.ip(address)
        return ip is not None and any(ip in network for network in self.trusted)

    def _once(self, key: tuple) -> bool:
        now = self.monotonic()
        if now - self.muted.get(key, -MUTE_SECONDS - 1) < MUTE_SECONDS:
            return False
        self.muted[key] = now
        return True

    def poll(self) -> list[Notice]:
        ts, notices = self.now_iso(), []
        own = self.local_addresses()
        rows = list(self.connections())
        listening = {}
        for row in rows:
            if row.get("direction") == "listen" and dev.scope(row.get("laddr")) != dev.SCOPE_LOCAL:
                listening[(row.get("process_name"), row.get("lport"))] = row
        if self.exposed is None:
            self.exposed = set(listening)  # the first look is the reference, not news
        for key, row in listening.items():
            if key not in self.exposed:
                self.exposed.add(key)
                reach = dev.SCOPE_LABELS[dev.scope(row.get("laddr"))][0].lower()
                notices.append(Notice(ts, "exposed", None, None, row.get("lport"), row.get("process_name"),
                                      f"{row.get('laddr')}, {reach}"))
        for row in rows:
            remote = row.get("raddr")
            network = dev.origin(remote)
            if (row.get("direction") != "inbound" or network not in {"lan", "internet"} or remote in own
                    or self._trusted(remote) or not self._once(("client", remote, row.get("lport")))):
                continue
            notices.append(Notice(ts, "client", network, remote, row.get("lport"), row.get("process_name"), ""))
        notices += self._firewall(ts)
        return notices

    def _firewall(self, ts: str) -> list[Notice]:
        notices, now = [], self.monotonic()
        for row in self.firewall():
            remote = row.get("src_ip")
            network = dev.origin(remote)
            if network not in {"lan", "internet"} or self._trusted(remote) or str(row.get("direction") or "").casefold() == "send":
                continue
            if row.get("proto") == "icmp":
                if self._once(("ping", remote, None)):
                    notices.append(Notice(ts, "ping", network, remote, None, None, ""))
                continue
            if row.get("action") != "DROP" or row.get("dst_port") is None:
                continue
            window = self.drops[remote]
            window.append((now, row["dst_port"]))
            while window and now - window[0][0] > SCAN_SECONDS:
                window.popleft()
            ports = {port for _, port in window}
            if len(ports) >= self.scan_ports and self._once(("scan", remote, None)):
                notices.append(Notice(ts, "scan", network, remote, None, None,
                                      f"{len(ports)} puertos en {SCAN_SECONDS // 60} min"))
        return notices
