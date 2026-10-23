# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Live network watch: who connects to this computer's servers, pings it or scans it, and new exposed servers.

The tray polls it every few seconds, so a notification arrives while it still matters, not at the next collection
cycle. Every notice is also stored for the Desarrollo page. Repeats are muted per (kind, address, port) for an hour.
"""
from __future__ import annotations

import ipaddress
import time
from collections import defaultdict, deque
from dataclasses import dataclass, replace
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
    remote_name: str | None = None

    def title(self, lang: str = "es") -> str:
        en = lang == "en"
        where = {"internet": "Internet", "lan": "local network" if en else "red local"}.get(self.network or "", "")
        return {
            "client": (f"Connection from {where}" if en else f"Conexión desde {where}"),
            "ping": (f"Ping from {where}" if en else f"Ping desde {where}"),
            "scan": (f"Port scan from {where}" if en else f"Escaneo de puertos desde {where}"),
            "exposed": ("New server exposed to the network" if en else "Nuevo servidor expuesto a la red"),
            "docker": ("Container in trouble" if en else "Contenedor con problemas"),
        }[self.kind]

    def message(self, lang: str = "es") -> str:
        en = lang == "en"
        process = self.process_name or "?"
        remote = f"{self.remote_ip} ({self.remote_name})" if (self.remote_name and self.remote_ip) else self.remote_ip
        if self.kind == "client":
            return (f"{remote} → port {self.lport} ({process})" if en
                    else f"{remote} → puerto {self.lport} ({process})")
        if self.kind == "ping":
            return f"{remote} " + ("checked whether this computer exists" if en else "comprobó si este equipo existe")
        if self.kind == "scan":
            return f"{remote}: {self.detail}"
        if self.kind == "docker":
            return f"{process}: {self.detail}"
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
                 trusted: tuple = (), scan_ports: int = 20, monotonic: Callable[[], float] = time.monotonic,
                 port_names: Callable[[], dict[int, str]] = dict):
        """`port_names()` maps host ports to Docker containers, so a client of com.docker.backend is named."""
        self.connections, self.firewall, self.local_addresses = connections, firewall, local_addresses
        self.port_names = port_names
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
            target = self.port_names().get(row.get("lport")) if dev.runtime(row.get("process_name")).key == "container" else None
            notices.append(Notice(ts, "client", network, remote, row.get("lport"), target or row.get("process_name"), ""))
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


class HostResolver:
    """Resolves IP hostnames with local-first lookup, reverse DNS fallback, and thread-safe caching."""

    def __init__(self, repository=None, query_repo=None, lookup: Callable[[str], list[str]] | None = None,
                 now_iso: Callable[[], str] | None = None, timeout: float = 1.5):
        self.repository, self.query_repo = repository, query_repo
        self.lookup = lookup
        self.now_iso = now_iso
        self.timeout = timeout
        self._cache: dict[str, str | None] = {}
        import threading
        self._lock = threading.Lock()

    def resolve(self, ip: str | None, config: object | None = None) -> str | None:
        if not ip or (config is not None and not getattr(config, "resolve_ip_hostnames", True)):
            return None
        with self._lock:
            if ip in self._cache:
                return self._cache[ip]

        # 1. Local DB first (labels, dns_cache, hosts, past reverse_dns)
        if self.query_repo:
            try:
                entries = self.query_repo.ip_names([ip])
                entry = entries.get(ip)
                if entry:
                    name = None
                    if entry.get("label"):
                        name = entry["label"]
                    else:
                        for source in ("dns_cache", "hosts", "reverse_dns"):
                            for item in entry.get("names", []):
                                if item.get("source") == source and item.get("name"):
                                    name = item["name"]
                                    break
                            if name:
                                break
                    if name:
                        with self._lock:
                            self._cache[ip] = name
                        return name
            except Exception:
                pass

        # 2. Reverse lookup
        lookup = self.lookup
        if lookup is None:
            try:
                from infrastructure.windows.ip_names import reverse_lookup
                lookup = reverse_lookup
            except ImportError:
                lookup = None

        found_name = None
        if lookup is not None:
            try:
                try:
                    names = lookup(ip, timeout=self.timeout)
                except TypeError:
                    names = lookup(ip)
                if names:
                    found_name = names[0]
                    if self.repository:
                        now = self.now_iso() if self.now_iso else time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
                        self.repository.save_ip_names(ip, names, "reverse_dns", now)
            except Exception:
                pass

        with self._lock:
            self._cache[ip] = found_name
        return found_name

