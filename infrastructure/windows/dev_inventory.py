"""What runs on this computer right now, for the Desarrollo page: sockets plus the processes behind them."""
from __future__ import annotations

from datetime import datetime, timezone

from domain import dev
from infrastructure.windows import live_network

def _details(process, runtime_key: str) -> dict:
    """The costly fields, only for the processes shown (psutil's ppid() walks every process on Windows)."""
    import psutil
    values = {}
    for name, read in (("ppid", process.ppid), ("created", process.create_time), ("memory", process.memory_info),
                       ("cmdline", process.cmdline)):
        try:
            values[name] = read()
        except (psutil.Error, OSError):
            values[name] = None
    command = " ".join(values["cmdline"] or [])
    return {"ppid": values["ppid"],
            "started": datetime.fromtimestamp(values["created"], timezone.utc).isoformat() if values["created"] else None,
            "memory_mb": round(values["memory"].rss / 1048576) if values["memory"] else None,
            "command": dev.redact_command(command) if command else None,
            "target": dev.java_target(command) if runtime_key == "java" else None}


def snapshot(now_iso: str | None = None) -> dict:
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    connections = live_network.connections(now_iso)
    serving = {row.get("pid") for row in connections if row.get("direction") == "listen"}
    import psutil

    names, processes = {}, []
    for process in psutil.process_iter(["pid", "name", "exe"], ad_value=None):
        info = process.info
        names[info["pid"]] = info.get("name")
        runtime = dev.runtime(info.get("name"), info.get("exe"))
        if runtime.key not in dev.DEV_RUNTIMES and info["pid"] not in serving:
            continue
        processes.append({"pid": info["pid"], "name": info.get("name"), "path": info.get("exe"),
                          **_details(process, runtime.key)})
    for row in processes:
        row["parent"] = names.get(row["ppid"])
    return {"taken_at": now_iso, "connections": connections, "processes": processes}
