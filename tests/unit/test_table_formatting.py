from interfaces.gui.table_formatting import filter_table_rows, format_local_datetime, format_table_rows


def test_iso_dates_are_rendered_in_a_readable_local_format():
    rendered = format_local_datetime("2026-10-07T20:31:42+00:00")

    assert isinstance(rendered, str)
    assert "T" not in rendered
    assert rendered.count(":") == 2
    assert rendered.split()[0].count("/") == 2


def test_only_known_date_columns_are_formatted():
    rows, date_columns = format_table_rows([
        {"ts": "2026-10-07T20:31:42+00:00", "detalle": "2026-10-07T20:31:42+00:00"}
    ])

    assert rows[0]["ts"] != "2026-10-07T20:31:42+00:00"
    assert rows[0]["detalle"] == "2026-10-07T20:31:42+00:00"
    assert date_columns == {"ts"}


def test_search_is_case_insensitive_and_can_be_limited_to_columns():
    rows = [{"proceso": "PowerShell", "ruta": "C:/Windows"},
            {"proceso": "python", "ruta": "C:/Work"}]

    assert filter_table_rows(rows, "POWER", ["proceso"]) == [rows[0]]
    assert filter_table_rows(rows, "windows", ["proceso"]) == []
    assert filter_table_rows(rows, "windows", ["ruta"]) == [rows[0]]


def test_date_columns_become_local_datetimes_that_sort_chronologically():
    from datetime import datetime, timezone

    rows, _ = format_table_rows([{"ts": "2026-10-01T10:00:00+00:00"}, {"ts": "2026-08-31T10:00:00+00:00"}])
    assert all(isinstance(row["ts"], datetime) and row["ts"].tzinfo is None for row in rows)
    # As DD/MM text, 31/08 would sort after 01/10
    assert sorted(row["ts"] for row in rows)[0].month == 8
    expected = datetime(2026, 10, 1, 10, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert rows[0]["ts"] == expected


def test_search_matches_dates_as_displayed():
    rows, _ = format_table_rows([{"ts": "2026-10-07T12:00:00+00:00", "proceso": "a"}])
    shown = format_local_datetime("2026-10-07T12:00:00+00:00")
    assert filter_table_rows(rows, shown.split()[0], ["ts"]) == rows


def test_chart_axes_use_local_time_not_utc():
    from datetime import datetime, timezone

    from interfaces.gui.table_formatting import local_series

    series = local_series(["2026-10-07T15:00:00+00:00"])
    expected = datetime(2026, 10, 7, 15, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert series.iloc[0].to_pydatetime() == expected
