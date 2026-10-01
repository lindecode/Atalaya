from __future__ import annotations

from pathlib import Path

from application.collect import CollectService
from domain.models import CollectionRequest, CollectionResult


class FixedClock:
    def now_iso(self) -> str:
        return "2026-10-01T12:00:00+00:00"


class NonAdminSystem:
    def is_admin(self) -> bool:
        return False


class FakeCollector:
    def __init__(self, name: str, status: str):
        self.name = name
        self.status = status

    def collect(self, request: CollectionRequest) -> CollectionResult:
        return CollectionResult(self.name, "connections", (), self.status, ("sin permiso",) if self.status == "skipped" else ())


class FakeRepository:
    database_path = Path("memory")

    def __init__(self):
        self.finished = None

    def initialize(self): pass
    def start_run(self, kind, started_at, is_admin): return 7
    def get_cursor(self, source): return None
    def save_collection(self, run_id, result, now): return len(result.items)
    def finish_run(self, run_id, finished_at, status, collectors): self.finished = (status, collectors)


def test_skipped_collector_makes_run_partial():
    repository = FakeRepository()
    service = CollectService(
        repository,
        (FakeCollector("ok", "ok"), FakeCollector("security", "skipped")),
        FixedClock(),
        NonAdminSystem(),
    )

    result = service.execute()

    assert result["status"] == "partial"
    assert repository.finished[0] == "partial"
    assert result["collectors"]["security"]["warnings"] == ["sin permiso"]
