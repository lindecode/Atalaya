from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from application.analyze import AnalyzeService
from domain.models import CollectionResult, EvidenceView, NetworkConnection, PersistenceItem
from domain.rules import catalog
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


NOW = datetime.now(timezone.utc)


def ts(seconds=0):
    return (NOW + timedelta(seconds=seconds)).isoformat()


class Clock:
    def now_iso(self): return datetime.now(timezone.utc).isoformat()


class System:
    def is_admin(self): return False


class OfflineAnalyzer:
    """Ollama down: keeps these tests about the rules and the baseline only."""
    model = "fake"
    def analyze(self, alerts):
        raise ConnectionError("Ollama apagado")


def _repository(tmp_path, **overrides):
    settings = replace(Settings(), database_path=tmp_path / "t.db", reports_dir=tmp_path / "r", **overrides)
    repository = SQLiteRepository(settings)
    repository.initialize()
    return settings, repository


def _seed(repository, port=9999, task="Updater"):
    run_id = repository.start_run("collect", ts(), False)
    listen = NetworkConnection(ts(), "psutil", "tcp", "listen", "0.0.0.0", port, None, None, "LISTEN", 1, "svc.exe", None, None)
    repository.save_collection(run_id, CollectionResult("c", "connections", (listen,), "ok"), ts())
    item = PersistenceItem(ts(), ts(), "scheduled_task", "\\", task, "x.exe")
    repository.save_collection(run_id, CollectionResult("p", "persistence_items", (item,), "ok"), ts())


def test_learning_runs_approve_what_they_see_then_new_things_alert(tmp_path):
    settings, repository = _repository(tmp_path, baseline_runs=1)
    _seed(repository)
    service = AnalyzeService(repository, OfflineAnalyzer(), Clock(), System(), settings)

    first = service.execute()
    assert first["learning"] and first["new_alerts"] == 0

    _seed(repository, port=4444, task="Malo")
    second = service.execute()
    assert not second["learning"]
    assert {alert["rule_id"] for alert in repository.get_alerts()} == {"R05", "R10"}
    assert len(repository.get_alerts()) == 2  # only the new port and the new task, not the learned ones


def test_bulk_learn_and_approve_alert_dismiss_covered_alerts(tmp_path):
    settings, repository = _repository(tmp_path, baseline_runs=0)
    _seed(repository)
    AnalyzeService(repository, OfflineAnalyzer(), Clock(), System(), settings).execute()
    alerts = repository.get_alerts()
    assert {a["rule_id"] for a in alerts} == {"R05", "R10"}

    port_alert = next(a for a in alerts if a["rule_id"] == "R05")
    assert repository.approve_alert(port_alert["id"], ts()) == ("listen_port", "svc.exe|9999")
    assert {a["rule_id"]: a["status"] for a in repository.get_alerts()} == {"R05": "dismissed", "R10": "new"}

    counts = repository.approve_all_observed(ts())
    assert counts["persistence"] == 1
    assert repository.dismiss_baselined("aprendida", ts()) == 1
    assert {a["status"] for a in repository.get_alerts()} == {"dismissed"}


def test_listen_port_alerts_once_not_every_hour():
    view = EvidenceView(connections=(
        {"id": 1, "ts": ts(), "direction": "listen", "process_name": "x", "lport": 1},
        {"id": 2, "ts": ts(7200), "direction": "listen", "process_name": "x", "lport": 1},
    ))
    alerts = catalog.r05(view, None)
    assert len(alerts) == 1 and alerts[0].window_key == "first"
