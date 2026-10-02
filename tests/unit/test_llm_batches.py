from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from application.analyze import AnalyzeService
from domain.models import CollectionResult, NetworkConnection, PersistenceItem
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


class Clock:
    def now_iso(self): return datetime.now(timezone.utc).isoformat()


class System:
    def is_admin(self): return False


class Analyzer:
    """Fails every call for a batch holding an R10 alert, succeeds otherwise."""
    model = "fake"
    def analyze(self, alerts):
        if any(alert["rule_id"] == "R10" for alert in alerts):
            raise ConnectionError("lote roto")
        return {"summary": "ok", "overall_risk": "low", "incidents": []}, 10, [int(alert["id"]) for alert in alerts]


def test_only_alerts_from_successful_batches_become_analyzed(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "t.db", reports_dir=tmp_path / "r",
                       baseline_runs=0, llm_batch_size=1, llm_max_alerts=3)
    repository = SQLiteRepository(settings)
    repository.initialize()
    now = Clock().now_iso()
    for port in (1, 2, 3, 4):
        run_id = repository.start_run("collect", now, False)
        listen = NetworkConnection(now, "psutil", "tcp", "listen", "0.0.0.0", port, None, None, "LISTEN", 1, "svc.exe", None, None)
        repository.save_collection(run_id, CollectionResult("c", "connections", (listen,), "ok"), now)
        task = PersistenceItem(now, now, "scheduled_task", "\\", f"t{port}", "x.exe")
        repository.save_collection(run_id, CollectionResult("p", "persistence_items", (task,), "ok"), now)

    result = AnalyzeService(repository, Analyzer(), Clock(), System(), settings).execute()

    alerts = repository.get_alerts()
    assert result["llm_alerts"] == 2
    # 4 x R05 + 1 x R10 (only the last task is still active); the R10 goes first by severity and its batch fails
    assert next(a["status"] for a in alerts if a["rule_id"] == "R10") == "new"
    assert sum(a["status"] == "analyzed" for a in alerts) == 2
    assert sum(a["status"] == "new" for a in alerts) == 3     # failed batch + beyond the cap: next run
    assert "lote roto" in result["llm_error"]
