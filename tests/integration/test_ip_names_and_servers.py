# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from domain.models import CollectionRequest, CollectionResult, EvidenceView, NetworkConnection
from domain.rules import catalog
from infrastructure.sqlite.queries import SQLiteQueryRepository
from infrastructure.sqlite.repositories import SQLiteRepository
from infrastructure.windows import ip_names
from settings import Settings

NOW = datetime.now(timezone.utc)
CACHE = [
    {"Entry": "www.example.com", "Data": "edge.example.net", "Type": 5},
    {"Entry": "edge.example.net", "Data": "93.184.216.34", "Type": 1},
    {"Entry": "blocked.example", "Data": "0.0.0.0", "Type": 1},
]


def _repository(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "net.db", reports_dir=tmp_path / "r")
    repository = SQLiteRepository(settings)
    repository.initialize()
    return settings, repository


def _connection(direction, laddr, lport, raddr, rport, process, minutes=0, state="ESTABLISHED", proto="tcp"):
    ts = (NOW - timedelta(minutes=minutes)).isoformat()
    return NetworkConnection(ts, "psutil", proto, direction, laddr, lport, raddr, rport, state, 1, process, None, None)


def test_names_come_from_cache_and_hosts_and_outlive_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ip_names, "is_windows", lambda: True)
    hosts = tmp_path / "hosts"
    hosts.write_text("# comment\n192.168.1.10  nas.local nas\n0.0.0.0 ads.example\n127.0.0.1 localhost\n", encoding="utf-8")
    collector = ip_names.IpNameCollector(lambda: CACHE, lambda: ip_names.hosts_pairs(hosts))
    result = collector.collect(CollectionRequest(NOW.isoformat()))
    pairs = {(item.ip, item.name, item.source) for item in result.items}
    assert pairs == {("93.184.216.34", "edge.example.net", "dns_cache"), ("93.184.216.34", "www.example.com", "dns_cache"),
                     ("192.168.1.10", "nas.local", "hosts"), ("192.168.1.10", "nas", "hosts")}

    settings, repository = _repository(tmp_path)
    run = repository.start_run("collect", NOW.isoformat(), False)
    assert repository.save_collection(run, result, NOW.isoformat()) == 4
    later = (NOW + timedelta(hours=1)).isoformat()
    again = CollectionResult("ip_names", "ip_names", tuple(replace(item, ts=later) for item in result.items[:1]), "ok")
    assert repository.save_collection(run, again, later) == 0  # same name: only last_seen moves
    names = SQLiteQueryRepository(settings).ip_names()
    assert {entry["name"] for entry in names["93.184.216.34"]["names"]} == {"edge.example.net", "www.example.com"}


def test_labels_are_set_and_cleared(tmp_path):
    settings, repository = _repository(tmp_path)
    repository.set_ip_label("192.168.1.1", "  Router   de casa ", NOW.isoformat())
    assert SQLiteQueryRepository(settings).ip_names()["192.168.1.1"]["label"] == "Router de casa"
    repository.set_ip_label("192.168.1.1", "", NOW.isoformat())
    assert "192.168.1.1" not in SQLiteQueryRepository(settings).ip_names()


def test_directory_and_servers_summarize_the_window(tmp_path):
    settings, repository = _repository(tmp_path)
    run = repository.start_run("collect", NOW.isoformat(), False)
    rows = (
        _connection("listen", "0.0.0.0", 3389, None, None, "svchost.exe", state="LISTEN"),
        _connection("inbound", "192.168.1.5", 3389, "8.8.4.4", 50000, "svchost.exe"),
        _connection("outbound", "192.168.1.5", 50001, "93.184.216.34", 443, "msedge.exe"),
        _connection("outbound", "127.0.0.1", 50002, "127.0.0.1", 9000, "local.exe"),
        _connection(None, "0.0.0.0", 55555, None, None, "dns-client.exe", proto="udp", state=None),  # as psutil reports UDP
    )
    repository.save_collection(run, CollectionResult("psutil_connections", "connections", rows, "ok"), NOW.isoformat())
    query = SQLiteQueryRepository(settings)
    since = (NOW - timedelta(hours=1)).isoformat()

    directory = {row["ip"]: row for row in query.ip_directory(since)}
    assert set(directory) == {"8.8.4.4", "93.184.216.34"}  # loopback is not a remote IP
    assert directory["8.8.4.4"]["directions"] == ["inbound"] and directory["8.8.4.4"]["ports"] == ["3389"]

    servers = query.servers(since)
    assert {(row["proto"], row["lport"]) for row in servers["listening"]} == {("tcp", 3389)}  # ephemeral UDP ignored
    assert [(row["lport"], row["raddr"]) for row in servers["clients"]] == [(3389, "8.8.4.4")]
    assert servers["now"] == [{"lport": 3389, "process_name": "svchost.exe", "connections": 1}]


def test_r17_alerts_once_per_internet_client_and_port_unless_approved():
    inbound = lambda raddr, minutes=0: {"id": minutes + 1, "ts": (NOW - timedelta(minutes=minutes)).isoformat(),
                                         "direction": "inbound", "raddr": raddr, "lport": 3389, "process_name": "svchost.exe"}
    view = EvidenceView(connections=(inbound("8.8.4.4"), inbound("8.8.4.4", 5), inbound("192.168.1.20")))
    alerts = catalog.r17(view, None)
    assert [alert.entity for alert in alerts] == ["8.8.4.4|3389"]  # once, and LAN clients do not count
    approved = EvidenceView(connections=view.connections, baseline=frozenset({("inbound_client", "8.8.4.4|3389")}))
    assert catalog.r17(approved, None) == []


def test_reverse_lookup_rejects_anything_that_is_not_an_ip():
    with pytest.raises(ValueError):
        ip_names.reverse_lookup("example.com; rm -rf /")
