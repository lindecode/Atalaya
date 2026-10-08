from __future__ import annotations

from datetime import datetime, timedelta, timezone

from interfaces.gui import page_views


def _ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def test_sources_are_judged_by_when_they_were_checked_not_by_new_data(monkeypatch):
    monkeypatch.setattr(page_views, "_cycle_config", lambda: (300, 3600))
    runs = [
        {"id": 3, "kind": "collect", "status": "partial", "started_at": _ago(2), "finished_at": _ago(1),
         "collectors": {"psutil_processes": {"status": "ok"}, "security_events": {"status": "ok"},
                        "windows_firewall": {"status": "skipped"}}},
        {"id": 2, "kind": "collect", "status": "ok", "started_at": _ago(50), "finished_at": _ago(49),
         "collectors": {"recent_files": {"status": "ok"}}},
        {"id": 1, "kind": "analyze", "status": "ok", "started_at": _ago(300), "finished_at": _ago(300), "collectors": {}},
    ]
    checks = {source: state for source, state, _, _ in page_views._source_checks(runs, {"Accesos": None})}
    assert checks["Procesos"] == "ok"
    assert checks["Accesos"] == "ok"        # checked a minute ago; no logons is normal
    assert checks["Firewall"] == "off"      # the collector could not read it
    assert checks["Archivos"] == "ok"       # 49 min is fine for the hourly standard profile
    assert checks["Conexiones"] == "none"   # not checked in these runs
    assert checks["Alertas"] == "stale"     # no analysis in 5 h
