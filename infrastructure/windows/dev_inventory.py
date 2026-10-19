# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""What runs on this computer right now, for the Desarrollo page: sockets plus the processes behind them."""
from __future__ import annotations

from datetime import datetime, timezone

from domain import dev
from domain.ssh_forwards import parse_command
from infrastructure.windows import live_network

SSH_CLIENTS = {"ssh.exe", "ssh"}


def _details(process, runtime_key: str, name: str | None = None) -> dict:
    """The costly fields, only for the processes shown (psutil's ppid() walks every process on Windows)."""
    import psutil
    values = {}
    for field, read in (("ppid", process.ppid), ("created", process.create_time), ("memory", process.memory_info),
                        ("cmdline", process.cmdline)):
        try:
            values[field] = read()
        except (psutil.Error, OSError):
            values[field] = None
    command = " ".join(values["cmdline"] or [])
    # Tunnels are read from the raw arguments (ports and targets only); the stored command stays redacted
    tunnels = parse_command(values["cmdline"]) if str(name or "").casefold() in SSH_CLIENTS and values["cmdline"] else None
    return {"ppid": values["ppid"], "ssh": tunnels,
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
        ssh_client = str(info.get("name") or "").casefold() in SSH_CLIENTS  # -R tunnels listen on the server, not here
        if runtime.key not in dev.DEV_RUNTIMES and info["pid"] not in serving and not ssh_client:
            continue
        processes.append({"pid": info["pid"], "name": info.get("name"), "path": info.get("exe"),
                          **_details(process, runtime.key, info.get("name"))})
    for row in processes:
        row["parent"] = names.get(row["ppid"])
    from infrastructure.windows.ssh_tunnels import ssh_config, vscode_forwards
    return {"taken_at": now_iso, "connections": connections, "processes": processes,
            "vscode_forwards": vscode_forwards(), "ssh_config": ssh_config()}
