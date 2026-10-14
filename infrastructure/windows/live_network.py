"""Live sources for the network watch: current sockets, this computer's addresses and the firewall log tail."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from domain.models import CollectionRequest
from infrastructure.windows.connections import PsutilConnectionCollector
from infrastructure.windows.firewall import FirewallLogCollector


def connections(now_iso: str) -> list[dict]:
    result = PsutilConnectionCollector().collect(CollectionRequest(now_iso))
    return [asdict(item) for item in result.items]


def local_addresses() -> set[str]:
    try:
        import psutil
        return {address.address.split("%")[0] for addresses in psutil.net_if_addrs().values() for address in addresses}
    except Exception:
        return set()


class FirewallTail:
    """New firewall log rows since the previous call; the first call starts at the end (history is not news)."""

    def __init__(self, path: Path):
        self.collector = FirewallLogCollector(path)
        self.cursor: dict | None = None

    def __call__(self, now_iso: str = "") -> list[dict]:
        if self.cursor is None:
            try:
                stat = self.collector.path.stat()
                self.cursor = {"offset": stat.st_size, "file_id": stat.st_ino}
            except OSError:
                self.cursor = {}
            return []
        result = self.collector.collect(CollectionRequest(now_iso, self.cursor))
        if result.next_cursor:
            self.cursor = result.next_cursor
        return [asdict(item) for item in result.items]


def firewall_readable(path: Path) -> bool:
    """MpsSvc recreates the log without the folder's read permission: existing is not enough."""
    try:
        path.open("rb").close()
        return True
    except OSError:
        return False
