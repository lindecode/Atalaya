from __future__ import annotations

import json
from pathlib import Path


def read_log_entries(path: Path, limit: int = 500) -> list[dict]:
    """Read bounded recent JSON entries, including rotated files, newest first."""
    limit = min(max(int(limit), 1), 2000)
    candidates = [path.with_name(path.name + f".{index}") for index in range(4, 0, -1)] + [path]
    entries: list[dict] = []
    for candidate in (item for item in candidates if item.is_file()):
        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                item = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(item, dict) and {"ts", "level", "message"} <= item.keys():
                entries.append(item)
    return sorted(entries, key=lambda item: str(item.get("ts", "")), reverse=True)[:limit]


def read_application_logs(directory: Path, limit: int = 500) -> list[dict]:
    """Merge every component log without allowing arbitrary paths from the UI."""
    limit = min(max(int(limit), 1), 2000)
    entries: list[dict] = []
    bases = sorted(directory.glob("atalaya-*.jsonl"))
    legacy = directory / "atalaya.jsonl"
    if legacy.is_file():
        bases.append(legacy)
    for base in bases:
        entries.extend(read_log_entries(base, limit))
    return sorted(entries, key=lambda item: str(item.get("ts", "")), reverse=True)[:limit]
