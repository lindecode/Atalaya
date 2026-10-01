from __future__ import annotations

from domain.models import EvidenceView
from application.analyze import AnalyzeService
from settings import Settings


class FixedClock:
    def now_iso(self): return "2026-10-01T12:00:00+00:00"


class System:
    def is_admin(self): return False


class FailingAnalyzer:
    model = "fake"
    calls = 0
    def analyze(self, alerts):
        self.calls += 1
        raise ConnectionError("Ollama apagado")


class Repository:
    def initialize(self): pass
    def start_run(self, *args): return 1
    def load_evidence(self, since): return EvidenceView()
    def observe_baseline(self, view, ts): pass
    def save_alerts(self, candidates): return []
    def get_new_alerts(self, limit=5000):
        return [{"id": 1, "rule_id": "R01", "severity": "high", "title": "x", "evidence": {}, "examples": []}]
    def save_llm_analysis(self, *args): self.saved = args
    def finish_run(self, *args): self.finished = args


def test_ollama_failure_retries_once_and_degrades():
    repository = Repository()
    analyzer = FailingAnalyzer()
    service = AnalyzeService(repository, analyzer, FixedClock(), System(), Settings(), rules=())
    result = service.execute()
    assert analyzer.calls == 2
    assert result["status"] == "partial"
    assert "Ollama apagado" in result["llm_error"]
    assert repository.saved[6] is not None

