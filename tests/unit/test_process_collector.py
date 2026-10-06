from __future__ import annotations

import sys
from types import SimpleNamespace

from domain.models import CollectionRequest
from infrastructure.windows.processes import PsutilProcessCollector


class Process:
    pid = 42
    def oneshot(self):
        class Context:
            def __enter__(self): return self
            def __exit__(self, *_): return None
        return Context()
    def create_time(self): return 1000.5
    def memory_info(self): return SimpleNamespace(rss=300, vms=900, private=200)
    def memory_full_info(self): return SimpleNamespace(uss=200)
    def io_counters(self): return SimpleNamespace(read_bytes=10, write_bytes=20)
    def parent(self): return SimpleNamespace(name=lambda: "parent.exe")
    def name(self): return "app.exe"
    def exe(self): return r"C:\Program Files\App\app.exe"
    def username(self): return "alice"
    def status(self): return "running"
    def ppid(self): return 1
    def cmdline(self): return ["app.exe", "--safe"]
    def cpu_times(self): return SimpleNamespace(user=2.0, system=1.0)
    def num_threads(self): return 4
    def memory_percent(self): return 1.5

    @property
    def info(self):
        return {"pid": self.pid, "create_time": self.create_time(), "name": self.name(), "exe": self.exe(),
                "username": self.username(), "status": self.status(), "ppid": self.ppid(), "cmdline": self.cmdline(),
                "memory_info": self.memory_info(), "memory_percent": self.memory_percent(),
                "cpu_times": self.cpu_times(), "num_threads": self.num_threads(), "io_counters": self.io_counters()}


def test_process_collector_uses_creation_time_and_private_memory(monkeypatch):
    error = type("PsutilError", (Exception,), {})
    fake = SimpleNamespace(process_iter=lambda *args, **kwargs: [Process()], AccessDenied=error, NoSuchProcess=error, ZombieProcess=error)
    monkeypatch.setitem(sys.modules, "psutil", fake)
    result = PsutilProcessCollector().collect(CollectionRequest("2026-10-06T12:00:00+00:00"))
    assert result.status == "ok" and len(result.items) == 1
    item = result.items[0]
    assert item.pid == 42 and item.private_bytes == 200 and item.rss_bytes == 300
    assert item.command_summary == "app.exe --safe" and len(item.process_key) == 64
