from __future__ import annotations

import socket
import sys
from types import SimpleNamespace

from domain.models import CollectionRequest
from infrastructure.windows.ssh import SSHObservationCollector, _safe_command


def test_safe_command_keeps_flags_but_discards_targets_and_remote_command():
    summary, tunnels, forwarding = _safe_command(
        "ssh.exe", ["ssh.exe", "-A", "-R", "9000:secret.internal:443", "user@host", "token=secret"]
    )
    assert summary == "ssh.exe -A -R"
    assert tunnels == "reverse"
    assert forwarding is True
    assert "secret" not in summary and "host" not in summary


def test_collector_finds_nonstandard_ssh_and_ignores_other_process(monkeypatch):
    ssh_connection = SimpleNamespace(laddr=("10.0.0.2", 50100), raddr=("203.0.113.8", 2222),
                                     type=socket.SOCK_STREAM, status="ESTABLISHED", pid=10)
    web_connection = SimpleNamespace(laddr=("10.0.0.2", 50101), raddr=("203.0.113.9", 443),
                                     type=socket.SOCK_STREAM, status="ESTABLISHED", pid=11)
    processes = {
        10: SimpleNamespace(name=lambda: "ssh.exe", exe=lambda: r"C:\Windows\ssh.exe",
                            username=lambda: "alice", cmdline=lambda: ["ssh.exe", "-D1080", "private-host"]),
        11: SimpleNamespace(name=lambda: "browser.exe", exe=lambda: r"C:\browser.exe",
                            username=lambda: "alice", cmdline=lambda: ["browser.exe"]),
    }
    fake = SimpleNamespace(
        net_connections=lambda kind: [ssh_connection, web_connection], Process=lambda pid: processes[pid],
        AccessDenied=type("AccessDenied", (Exception,), {}), NoSuchProcess=type("NoSuchProcess", (Exception,), {}),
        ZombieProcess=type("ZombieProcess", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "psutil", fake)
    monkeypatch.setattr("infrastructure.windows.ssh.os.name", "posix")
    result = SSHObservationCollector().collect(CollectionRequest("2026-10-02T12:00:00+00:00"))
    assert len(result.items) == 1
    assert result.items[0].remote_port == 2222
    assert result.items[0].tunnel_types == "socks"
    assert "private-host" not in (result.items[0].command_summary or "")
