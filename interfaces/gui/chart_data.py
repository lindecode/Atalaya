"""Data shaping for the GUI charts (pure: no Streamlit, tested directly)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

import pandas as pd

from interfaces.gui.table_formatting import local_series

MAX_HOURS = 24 * 31  # longest window offered (30 days) plus margin


def _utc_hour(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def hourly_frame(points: Iterable[Mapping[str, object]], since: str, *, time_key: str, value_key: str,
                 series_key: str | None = None, now: datetime | None = None) -> pd.DataFrame:
    """One row per hour of the window (and per series), with 0 where nothing happened, on local-time axes.

    SQLite groups by UTC hour; quiet hours are simply missing there, which made bars jump and hid gaps.
    """
    points = list(points)
    end = _utc_hour(now or datetime.now(timezone.utc))
    start = max(_utc_hour(since), end - timedelta(hours=MAX_HOURS))
    hours = [start + timedelta(hours=offset) for offset in range(int((end - start) / timedelta(hours=1)) + 1)]
    counts: dict[tuple, float] = {}
    for point in points:
        hour = _utc_hour(str(point[time_key]))
        series = str(point[series_key]) if series_key else None
        counts[(hour, series)] = counts.get((hour, series), 0) + float(point[value_key] or 0)
    series_values = sorted({series for _, series in counts}, key=str) if series_key else [None]
    hours = sorted(set(hours) | {hour for hour, _ in counts})
    rows = [{time_key: hour.isoformat(), value_key: counts.get((hour, series), 0),
             **({series_key: series} if series_key else {})}
            for series in series_values for hour in hours]
    frame = pd.DataFrame(rows, columns=[time_key, value_key] + ([series_key] if series_key else []))
    frame[time_key] = local_series(frame[time_key])
    return frame
