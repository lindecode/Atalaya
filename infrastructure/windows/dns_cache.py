"""Names this computer recently resolved, read from the local Windows DNS client cache (no network queries)."""
from __future__ import annotations

import json
import subprocess

from infrastructure.windows.common import is_windows

ADDRESS_TYPES = {1, 28}  # A, AAAA
CNAME = 5
SCRIPT = ("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
          "Get-DnsClientCache -ErrorAction SilentlyContinue | Select-Object Entry,Data,Type | ConvertTo-Json -Compress")


def dns_cache_records(timeout: float = 15) -> list[dict]:
    """[{Entry, Data, Type}] from Get-DnsClientCache; empty when unavailable. The script is fixed: no input in it."""
    if not is_windows():
        return []
    try:
        completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SCRIPT],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                   check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        parsed = json.loads(completed.stdout) if completed.returncode == 0 and completed.stdout.strip() else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return [record for record in (parsed if isinstance(parsed, list) else [parsed]) if isinstance(record, dict)]


def names_for(address: str, records: list[dict]) -> list[str]:
    """Host names that resolved to `address`, plus the aliases (CNAME) that led to them, most specific first."""
    target = str(address).casefold()
    direct = {str(r.get("Entry")).casefold() for r in records
              if r.get("Type") in ADDRESS_TYPES and str(r.get("Data")).casefold() == target and r.get("Entry")}
    names, pending = set(direct), set(direct)
    while pending:  # walk CNAME chains backwards: alias -> canonical name -> address
        aliases = {str(r.get("Entry")).casefold() for r in records
                   if r.get("Type") == CNAME and str(r.get("Data")).casefold() in pending and r.get("Entry")}
        pending = aliases - names
        names |= aliases
    return sorted(names, key=lambda name: (name not in direct, name))
