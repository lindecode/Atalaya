from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Iterable

from domain.models import AlertCandidate, EvidenceRef


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def refs(entity_type: str, rows: Iterable[dict[str, Any]]) -> tuple[EvidenceRef, ...]:
    return tuple(EvidenceRef(entity_type, int(row["id"]), dict(row)) for row in rows)


def candidate(rule_id: str, severity: str, title: str, entity: str, rows, entity_type: str, summary, ts: str, bucket: str | None = None):
    key_bucket = bucket or dt(ts).strftime("%Y%m%d%H")
    return AlertCandidate(ts, rule_id, severity, title, entity, summary, refs(entity_type, rows), key_bucket)


def has_distinct_window(rows: list[dict[str, Any]], key: str, count: int, minutes: int) -> list[dict[str, Any]] | None:
    """First window of `minutes` holding at least `count` distinct values of `key` (e.g. ports in a scan)."""
    ordered = sorted(rows, key=lambda row: dt(row["ts"]))
    span = timedelta(minutes=minutes)
    seen: Counter = Counter()
    left = 0
    for right, row in enumerate(ordered):
        seen[row.get(key)] += 1
        while dt(row["ts"]) - dt(ordered[left]["ts"]) > span:
            old = ordered[left].get(key)
            seen[old] -= 1
            if not seen[old]:
                del seen[old]
            left += 1
        if len(seen) >= count:
            return ordered[left:right + 1]
    return None


def baseline_key(rule_id: str, row: dict[str, Any]) -> tuple[str, str] | None:
    """Baseline entry that would make this rule ignore `row`; shared by rules, learning and approval."""
    if rule_id in {"R03", "R04"}:
        ip = row.get("source_ip")
        return ("logon_source", str(ip)) if ip and ip not in INVALID_IPS else None
    if rule_id == "R05":
        return ("listen_port", f"{row.get('process_name') or '?'}|{row.get('lport')}")
    if rule_id == "R10" and row.get("kind"):
        return ("persistence", f"{row['kind']}|{row.get('location') or ''}|{row.get('name') or ''}")
    return None


INVALID_IPS = {"", "-", "::1", "127.0.0.1", "None"}


def has_window(rows: list[dict[str, Any]], count: int, minutes: int) -> list[dict[str, Any]] | None:
    ordered = sorted(rows, key=lambda row: dt(row["ts"]))
    span = timedelta(minutes=minutes)
    left = 0
    for right, row in enumerate(ordered):
        while dt(row["ts"]) - dt(ordered[left]["ts"]) > span:
            left += 1
        if right - left + 1 >= count:
            return ordered[left:right + 1]
    return None

