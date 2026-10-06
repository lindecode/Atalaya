from __future__ import annotations

import hashlib

from domain.models import CollectionRequest, CollectionResult, ProcessSnapshot


def _text(parts: list[str], limit: int = 500) -> str | None:
    value = " ".join(str(part).replace("\x00", " ") for part in parts if part)
    return " ".join(value.split())[:limit] or None


class PsutilProcessCollector:
    """A point-in-time, read-only process inventory. Process identity includes creation time."""

    name = "psutil_processes"

    def collect(self, request: CollectionRequest) -> CollectionResult:
        try:
            import psutil
        except ImportError:
            return CollectionResult(self.name, "process_snapshots", (), "skipped", ("psutil no está instalado",))
        attributes = ("pid", "create_time", "name", "exe", "username", "status", "ppid", "cmdline",
                      "memory_info", "memory_percent", "cpu_times", "num_threads", "io_counters")
        items, denied = [], 0
        processes = list(psutil.process_iter(attributes, ad_value=None))
        names = {process.info["pid"]: process.info.get("name") for process in processes}
        for process in processes:
            try:
                info = process.info
                created, memory = info.get("create_time"), info.get("memory_info")
                if created is None or memory is None:
                    denied += 1; continue
                created = float(created)
                private = getattr(memory, "private", None)
                io, cpu = info.get("io_counters"), info.get("cpu_times")
                key = hashlib.sha256(f"{process.pid}:{created:.6f}".encode("ascii")).hexdigest()
                items.append(ProcessSnapshot(
                    request.now, key, process.pid, created, info.get("name"), info.get("exe"), info.get("username"),
                    info.get("status"), info.get("ppid"), names.get(info.get("ppid")), _text(info.get("cmdline") or []),
                    int(memory.rss), int(private) if private is not None else None, int(memory.vms),
                    round(float(info.get("memory_percent") or 0), 4),
                    round(float((cpu.user + cpu.system) if cpu else 0), 3), int(info.get("num_threads") or 0),
                    int(io.read_bytes) if io else None, int(io.write_bytes) if io else None,
                ))
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
                denied += 1
        warnings = (f"{denied} proceso(s) no pudieron leerse por permisos o porque terminaron",) if denied else ()
        # A process may disappear between process_iter() and reading its fields; that is expected in a valid
        # point-in-time snapshot. Keep the snapshot authoritative so lifecycle can mark missing identities ended.
        return CollectionResult(self.name, "process_snapshots", tuple(items), "ok", warnings)
