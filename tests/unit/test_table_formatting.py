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
