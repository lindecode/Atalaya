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
