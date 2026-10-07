from __future__ import annotations

from datetime import datetime, timezone

from interfaces.gui.chart_data import hourly_frame
from interfaces.gui.table_views import HIDDEN, VIEWS, present, visible


NOW = datetime(2026, 10, 7, 15, 30, tzinfo=timezone.utc)


def _local(hour: int) -> datetime:
    return datetime(2026, 10, 7, hour, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def test_hourly_frame_fills_quiet_hours_with_zero_in_local_time():
    points = [{"hora": "2026-10-07T12:00:00+00:00", "total": 4}, {"hora": "2026-10-07T15:00:00+00:00", "total": 1}]
    frame = hourly_frame(points, "2026-10-07T11:30:00+00:00", time_key="hora", value_key="total", now=NOW)
    assert list(frame["hora"]) == [_local(hour) for hour in (11, 12, 13, 14, 15)]
    assert list(frame["total"]) == [0, 4, 0, 0, 1]


def test_hourly_frame_completes_every_series_and_accepts_buckets_without_offset():
    points = [{"bucket": "2026-10-07T14:00:00", "count": 3, "type": "alertas"},
              {"bucket": "2026-10-07T15:00:00", "count": 9, "type": "conexiones"}]
    frame = hourly_frame(points, "2026-10-07T14:00:00+00:00", time_key="bucket", value_key="count",
                         series_key="type", now=NOW)
    assert len(frame) == 4  # 2 hours x 2 series
    alerts = frame[frame["type"] == "alertas"].sort_values("bucket")
    assert list(alerts["count"]) == [3, 0]


def test_views_translate_and_hide_internal_columns():
    row = {"id": 7, "ts": "2026-10-07T15:00:00+00:00", "event_id": 4625, "logon_type": 10, "target_user": "ana",
           "source_ip": "203.0.113.5", "raw_xml": "<Event/>", "record_id": 99}
    shown = present([row], "auth_events")[0]
    assert shown["Evento"] == "Inicio fallido (4625)" and shown["Tipo de inicio"] == "Remoto (RDP)"
    assert shown["Fecha"] == _local(15)
    assert "raw_xml" not in shown and "id" not in shown and "record_id" not in shown
    assert not any(column.source in HIDDEN for columns in VIEWS.values() for column in columns)


def test_reputation_reasons_and_generic_tables():
    shown = present([{"verdict": "likely_safe", "confidence": 0.85, "reasons_json": '["Firma válida", "Sin detecciones"]'}],
                    "file_reputation")[0]
    assert shown["Veredicto"] == "Probablemente seguro" and shown["Motivos"] == "Firma válida · Sin detecciones"
    assert visible({"a": 1, "dedup_key": "x", "run_id": 3}) == {"a": 1}
