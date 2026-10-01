from __future__ import annotations

import hashlib
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

