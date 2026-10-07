from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Mapping


DATE_COLUMNS = {
    "ts", "bucket", "hora", "created_at", "updated_at", "checked_at",
    "started_at", "finished_at", "first_seen", "last_seen", "ended_at",
    "last_missing_at",
}


def is_date_column(name: str) -> bool:
    normalized = name.strip().casefold().replace(" ", "_")
    return normalized in DATE_COLUMNS or normalized.endswith(("_at", "_seen"))


def format_local_datetime(value: object) -> object:
    """Turn an ISO-8601 value into a stable, readable local timestamp."""
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%d/%m/%Y %H:%M:%S")


def format_table_rows(rows: Iterable[Mapping[str, object]]) -> tuple[list[dict[str, object]], set[str]]:
    formatted: list[dict[str, object]] = []
    date_columns: set[str] = set()
    for source in rows:
        row = dict(source)
        for name, value in row.items():
            if is_date_column(name):
                row[name] = format_local_datetime(value)
                date_columns.add(name)
        formatted.append(row)
    return formatted, date_columns


def filter_table_rows(rows: Iterable[Mapping[str, object]], text: str,
                      columns: Iterable[str]) -> list[dict[str, object]]:
    values = [dict(row) for row in rows]
    needle = text.casefold().strip()
    selected = tuple(columns)
    if not needle or not selected:
        return values if not needle else []
    return [row for row in values if any(needle in str(row.get(column, "")).casefold()
                                         for column in selected)]
