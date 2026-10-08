import json
import logging
import sys

from infrastructure.log_reader import read_application_logs, read_log_entries
from infrastructure.logging_config import JsonFormatter, redact


def test_log_formatter_redacts_credentials_and_keeps_exception():
    try:
        raise ValueError("password=supersecret")
    except ValueError:
        record = logging.LogRecord("atalaya.test", logging.ERROR, __file__, 1,
                                   "falló api_key=%s", ("abcdef",), sys.exc_info())
    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "ERROR" and payload["logger"] == "atalaya.test"
    assert "abcdef" not in payload["message"] and "supersecret" not in payload["exception"]
    assert "[REDACTADO]" in payload["message"] and "ValueError" in payload["exception"]


def test_log_reader_skips_invalid_lines_and_bounds_results(tmp_path):
    path = tmp_path / "atalaya.jsonl"
    path.write_text("not-json\n" + "\n".join(json.dumps({"ts": str(i), "level": "ERROR", "message": str(i)})
                                                     for i in range(4)), encoding="utf-8")

    entries = read_log_entries(path, 2)

    assert [entry["message"] for entry in entries] == ["3", "2"]
    assert redact("Authorization: Bearer secret") == "Authorization: Bearer [REDACTADO]"


def test_application_reader_merges_component_logs(tmp_path):
    for component, stamp in (("gui", "2026-01-01T00:00:00+00:00"), ("tray", "2026-01-02T00:00:00+00:00")):
        (tmp_path / f"atalaya-{component}.jsonl").write_text(
            json.dumps({"ts": stamp, "level": "INFO", "message": component}), encoding="utf-8")

    assert [entry["message"] for entry in read_application_logs(tmp_path)] == ["tray", "gui"]
