"""Where SSH tunnels are declared: VS Code Remote-SSH forwarded ports and ~/.ssh/config (read-only, local files).

Nothing here is stored: the Desarrollo page reads it live to explain which local port leads where.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from domain.ssh_forwards import parse_config

VSCODE_KEY = "remote.tunnels.toRestore.ssh-remote+"
EDITIONS = ("Code", "Code - Insiders", "VSCodium", "Cursor")


def _alias(authority: str) -> str | None:
    """'7b22686f73744e616d65223a22...'227d' (hex JSON) or a plain alias -> the SSH host alias."""
    try:
        return json.loads(bytes.fromhex(authority).decode("utf-8")).get("hostName")
    except (ValueError, AttributeError):
        return authority or None


def vscode_forwards(appdata: str | None = None) -> list[dict]:
    """Ports VS Code forwards for each Remote-SSH host (auto-detected or added by hand)."""
    base = Path(appdata or os.environ.get("APPDATA", ""))
    found = []
    for edition in EDITIONS:
        database = base / edition / "User" / "globalStorage" / "state.vscdb"
        if not database.exists():
            continue
        try:
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=1) as db:
                rows = db.execute("SELECT key, value FROM ItemTable WHERE key LIKE ?", (VSCODE_KEY + "%",)).fetchall()
        except sqlite3.Error:
            continue
        for key, value in rows:
            authority = key[len(VSCODE_KEY):].rsplit(".", 1)[0]
            try:
                entries = json.loads(value if isinstance(value, str) else value.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            for entry in entries if isinstance(entries, list) else []:
                if not str(entry.get("localPort", "")).isdigit():
                    continue
                found.append({"kind": "local", "listen": int(entry["localPort"]), "bind": None,
                              "target": f"{entry.get('remoteHost') or 'localhost'}:{entry.get('remotePort')}",
                              "host": _alias(authority), "via": edition,
                              "auto": (entry.get("source") or {}).get("source") == 1})
    return found


def ssh_config(home: str | None = None) -> list[dict]:
    path = Path(home or Path.home()) / ".ssh" / "config"
    try:
        return parse_config(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []
