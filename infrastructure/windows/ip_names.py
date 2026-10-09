"""Names for IPs from local sources only: the DNS client cache (saved each collection so names outlive it) and hosts.

An explicit reverse lookup (reverse_lookup) does send a query to the configured DNS server and only runs on request.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

from domain.models import CollectionRequest, CollectionResult, IpName
from infrastructure.windows.common import is_windows
from infrastructure.windows.dns_cache import ADDRESS_TYPES, dns_cache_records, names_for

HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?$")
HOSTS_LIMIT = 5000
NOT_NAMED = {"0.0.0.0", "::", "127.0.0.1", "::1"}  # ad-block style hosts entries and loopback say nothing


def valid_ip(text: str) -> str | None:
    try:
        return str(ipaddress.ip_address(str(text).strip().split("%")[0]))
    except ValueError:
        return None


def _clean_name(name: str) -> str | None:
    name = str(name).strip().rstrip(".").casefold()
    return name if HOSTNAME.match(name) else None


def dns_cache_pairs(records: list[dict]) -> set[tuple[str, str]]:
    """(ip, name) for every address in the cache, aliases included."""
    pairs = set()
    for ip in {str(record.get("Data")) for record in records if record.get("Type") in ADDRESS_TYPES}:
        address = valid_ip(ip)
        if not address or address in NOT_NAMED:
            continue
        for name in names_for(ip, records):
            clean = _clean_name(name)
            if clean:
                pairs.add((address, clean))
    return pairs


def hosts_pairs(path: Path | None = None) -> set[tuple[str, str]]:
    path = path or Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    pairs = set()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return pairs
    for line in lines:
        fields = line.split("#", 1)[0].split()
        if len(fields) < 2:
            continue
        address = valid_ip(fields[0])
        if not address or address in NOT_NAMED:
            continue
        for name in fields[1:]:
            clean = _clean_name(name)
            if clean:
                pairs.add((address, clean))
        if len(pairs) >= HOSTS_LIMIT:
            break
    return pairs


class IpNameCollector:
    name = "ip_names"

    def __init__(self, cache_reader=dns_cache_records, hosts_reader=hosts_pairs):
        self.cache_reader, self.hosts_reader = cache_reader, hosts_reader

    def collect(self, request: CollectionRequest) -> CollectionResult:
        if not is_windows():
            return CollectionResult(self.name, "ip_names", (), "skipped", ("Solo disponible en Windows",))
        items = [IpName(request.now, ip, name, "dns_cache") for ip, name in sorted(dns_cache_pairs(self.cache_reader()))]
        items += [IpName(request.now, ip, name, "hosts") for ip, name in sorted(self.hosts_reader())]
        return CollectionResult(self.name, "ip_names", tuple(items), "ok")


def reverse_lookup(ip: str, timeout: float = 3.0) -> list[str]:
    """PTR names for one IP. Sends a query to the configured DNS server: call it only when the person asks."""
    address = valid_ip(ip)
    if not address:
        raise ValueError("IP no válida")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(socket.gethostbyaddr, address)
        try:
            host, aliases, _ = future.result(timeout=timeout)
        except FutureTimeout:
            raise TimeoutError("El servidor DNS no respondió a tiempo") from None
        except (socket.herror, socket.gaierror):
            return []
    names = [_clean_name(name) for name in [host, *aliases]]
    return sorted({name for name in names if name})
