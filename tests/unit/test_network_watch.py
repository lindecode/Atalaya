# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from application.automation import AutomationConfig
from application.network_watch import NetworkWatcher, Notice, parse_trusted
from infrastructure.sqlite.network_notices import SQLiteNetworkNotices
from infrastructure.sqlite.repositories import SQLiteRepository
from interfaces.tray import NetworkWatchLoop
from settings import Settings

NOW = "2026-10-14T12:00:00+00:00"


class Feed:
    """Mutable connection and firewall rows, plus a clock the test moves by hand."""

    def __init__(self):
        self.rows, self.firewall, self.clock = [], [], 0.0

    def watcher(self, **kwargs):
        def drain():
            rows, self.firewall = self.firewall, []
            return rows
        return NetworkWatcher(lambda: list(self.rows), drain, lambda: {"192.168.1.10"}, lambda: NOW,
                              monotonic=lambda: self.clock, **kwargs)


def _inbound(ip, port=8080, process="java.exe"):
    return {"direction": "inbound", "raddr": ip, "lport": port, "process_name": process, "laddr": "0.0.0.0"}


def _listen(port, address="0.0.0.0", process="node.exe"):
    return {"direction": "listen", "laddr": address, "lport": port, "process_name": process}


def test_clients_from_lan_and_internet_notify_once_per_hour_but_not_localhost_or_self():
    feed = Feed()
    watcher = feed.watcher()
    feed.rows = [_inbound("192.168.1.20"), _inbound("8.8.8.8"), _inbound("127.0.0.1"), _inbound("192.168.1.10")]
    notices = watcher.poll()
    assert [(n.kind, n.network, n.remote_ip) for n in notices] == [("client", "lan", "192.168.1.20"),
                                                                    ("client", "internet", "8.8.8.8")]
    assert watcher.poll() == []                     # same clients, still connected: muted
    feed.clock += 3601
    assert len(watcher.poll()) == 2                 # an hour later they are news again
    assert "8.8.8.8 → puerto 8080 (java.exe)" in notices[1].message()
    assert notices[1].title("en") == "Connection from Internet"


def test_trusted_addresses_never_notify():
    feed = Feed()
    watcher = feed.watcher(trusted=parse_trusted("192.168.1.0/24, 8.8.4.4"))
    feed.rows = [_inbound("192.168.1.20"), _inbound("8.8.4.4"), _inbound("1.1.1.1")]
    assert [n.remote_ip for n in watcher.poll()] == ["1.1.1.1"]
    with pytest.raises(ValueError, match="no válida: mi-celular"):
        parse_trusted("192.168.1.5, mi-celular")
    with pytest.raises(ValueError):
        AutomationConfig(trusted_ips="300.1.1.1").validated()


def test_only_servers_exposed_after_the_first_look_are_news():
    feed = Feed()
    watcher = feed.watcher()
    feed.rows = [_listen(3000), _listen(5173, "127.0.0.1")]
    assert watcher.poll() == []                      # already there when the watch started
    feed.rows += [_listen(8081, "::", "java.exe"), _listen(9000, "127.0.0.1")]
    notices = watcher.poll()
    assert [(n.kind, n.lport, n.process_name) for n in notices] == [("exposed", 8081, "java.exe")]


def test_pings_and_port_scans_from_the_firewall_log():
    feed = Feed()
    watcher = feed.watcher(scan_ports=5)
    feed.firewall = [{"proto": "icmp", "action": "DROP", "src_ip": "192.168.1.1", "direction": "RECEIVE"},
                     {"proto": "icmp", "action": "DROP", "src_ip": "192.168.1.1", "direction": "RECEIVE"},
                     {"proto": "icmp", "action": "DROP", "src_ip": "192.168.1.10", "direction": "SEND"}]
    assert [(n.kind, n.remote_ip) for n in watcher.poll()] == [("ping", "192.168.1.1")]
    feed.firewall = [{"proto": "tcp", "action": "DROP", "src_ip": "45.1.2.3", "dst_port": port, "direction": "RECEIVE"}
                     for port in range(20, 24)]
    assert watcher.poll() == []                      # 4 ports: not yet a scan
    feed.clock += 30
    feed.firewall = [{"proto": "tcp", "action": "DROP", "src_ip": "45.1.2.3", "dst_port": 25, "direction": "RECEIVE"}]
    scan = watcher.poll()
    assert [(n.kind, n.network, n.remote_ip) for n in scan] == [("scan", "internet", "45.1.2.3")]
    assert "5 puertos" in scan[0].message()


def test_loop_stores_everything_and_notifies_only_when_enabled(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "n.db")
    SQLiteRepository(settings).initialize()
    store = SQLiteNetworkNotices(settings)
    notices = [Notice(NOW, "client", "lan", f"192.168.1.{i}", 8080, "java.exe", "") for i in range(5)]
    toasts = []
    config = SimpleNamespace(network_notifications=True, trusted_ips="", language="es")
    loop = NetworkWatchLoop(SimpleNamespace(poll=lambda: notices, trusted=()), store,
                            lambda title, message: toasts.append((title, message)), lambda: config)
    loop.step()
    assert len(toasts) == NetworkWatchLoop.MAX_TOASTS + 1 and "2 avisos de red más" in toasts[-1][1]
    assert len(store.recent("2026-01-01")) == 5

    toasts.clear()
    loop.config, loop.loaded_at = SimpleNamespace(network_notifications=False, trusted_ips="", language="es"), loop.monotonic()
    loop.step()
    assert toasts == [] and len(store.recent("2026-01-01")) == 10


def test_notice_message_formats_with_remote_name():
    client_notice = Notice(NOW, "client", "lan", "192.168.1.50", 8080, "python.exe", "", remote_name="my-laptop")
    assert client_notice.message("es") == "192.168.1.50 (my-laptop) → puerto 8080 (python.exe)"
    assert client_notice.message("en") == "192.168.1.50 (my-laptop) → port 8080 (python.exe)"

    ping_notice = Notice(NOW, "ping", "lan", "192.168.1.1", None, None, "", remote_name="router.local")
    assert ping_notice.message("es") == "192.168.1.1 (router.local) comprobó si este equipo existe"
    assert ping_notice.message("en") == "192.168.1.1 (router.local) checked whether this computer exists"

    scan_notice = Notice(NOW, "scan", "internet", "45.1.2.3", None, None, "20 puertos en 2 min", remote_name="scanner.org")
    assert scan_notice.message("es") == "45.1.2.3 (scanner.org): 20 puertos en 2 min"
    assert scan_notice.message("en") == "45.1.2.3 (scanner.org): 20 puertos en 2 min"


def test_host_resolver_uses_cache_and_db_and_lookup():
    from application.network_watch import HostResolver

    # 1. Config with resolve_ip_hostnames=False returns None immediately
    resolver = HostResolver(lookup=lambda ip: ["resolved.host"])
    assert resolver.resolve("192.168.1.50", config=SimpleNamespace(resolve_ip_hostnames=False)) is None

    # 2. Local DB hit
    class FakeQueryRepo:
        def ip_names(self, ips):
            if "192.168.1.10" in ips:
                return {"192.168.1.10": {"label": "NAS", "names": []}}
            return {}

    lookup_called = []
    saved_names = []
    class FakeRepo:
        def save_ip_names(self, ip, names, source, ts):
            saved_names.append((ip, names, source))

    resolver = HostResolver(repository=FakeRepo(), query_repo=FakeQueryRepo(),
                            lookup=lambda ip, timeout=1.5: lookup_called.append(ip) or ["reverse.host"])
    # 192.168.1.10 resolves from FakeQueryRepo without calling lookup
    assert resolver.resolve("192.168.1.10") == "NAS"
    assert lookup_called == []

    # 192.168.1.20 not in FakeQueryRepo -> calls lookup and saves to repo
    assert resolver.resolve("192.168.1.20") == "reverse.host"
    assert lookup_called == ["192.168.1.20"]
    assert saved_names == [("192.168.1.20", ["reverse.host"], "reverse_dns")]

    # Second call for 192.168.1.20 uses in-memory cache
    lookup_called.clear()
    assert resolver.resolve("192.168.1.20") == "reverse.host"
    assert lookup_called == []


def test_network_watch_loop_enriches_notices_with_resolved_hostnames(tmp_path):
    from application.network_watch import HostResolver
    settings = replace(Settings(), database_path=tmp_path / "n2.db")
    SQLiteRepository(settings).initialize()
    store = SQLiteNetworkNotices(settings)
    notices = [Notice(NOW, "scan", "internet", "45.1.2.3", None, None, "15 puertos en 2 min")]
    toasts = []
    config = SimpleNamespace(network_notifications=True, resolve_ip_hostnames=True, trusted_ips="", language="es")
    resolver = HostResolver(lookup=lambda ip, timeout=1.5: ["scanner.test"])
    loop = NetworkWatchLoop(SimpleNamespace(poll=lambda: notices, trusted=()), store,
                            lambda title, message: toasts.append((title, message)), lambda: config,
                            resolver=resolver)
    result = loop.step()
    assert result[0].remote_name == "scanner.test"
    assert "45.1.2.3 (scanner.test): 15 puertos en 2 min" in toasts[0][1]

