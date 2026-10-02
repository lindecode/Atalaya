from __future__ import annotations

import time
from datetime import datetime, timedelta

from domain.rules import ALL_RULES
from ports.clock import Clock
from ports.llm import StructuredAnalyzer
from ports.repositories import AnalysisRepository
from ports.system import SystemInfo
from settings import Settings


class AnalyzeService:
    def __init__(self, repository: AnalysisRepository, analyzer: StructuredAnalyzer, clock: Clock,
                 system_info: SystemInfo, settings: Settings, rules=ALL_RULES):
        self.repository = repository
        self.analyzer = analyzer
        self.clock = clock
        self.system_info = system_info
        self.settings = settings
        self.rules = tuple(rules)

    def execute(self) -> dict[str, object]:
        self.repository.initialize()
        started = self.clock.now_iso()
        run_id = self.repository.start_run("analyze", started, self.system_info.is_admin())
        since = (datetime.fromisoformat(started) - timedelta(hours=self.settings.rule_window_hours)).isoformat()
        view = self.repository.load_evidence(since)
        # The first `baseline_runs` analyses learn what this machine looks like before the baseline rules fire
        learning = self.repository.count_runs("analyze") <= self.settings.baseline_runs
        if learning:
            self.repository.observe_baseline(view, started, approve=True)
            view = self.repository.load_evidence(since)
        candidates = [candidate for rule in self.rules for candidate in rule(view, self.settings)]
        if not learning:
            self.repository.observe_baseline(view, self.clock.now_iso())
        inserted = self.repository.save_alerts(candidates)
        alerts = self.repository.get_new_alerts(limit=5000)
        error = None
        result = None
        prompt_chars = 0
        begin = time.perf_counter()
        if alerts:
            batch_results = []
            errors = []
            batch_size = 5
            for offset in range(0, len(alerts), batch_size):
                batch = alerts[offset:offset + batch_size]
                try:
                    batch_result, chars = self.analyzer.analyze(batch)
                    batch_results.append(batch_result)
                    prompt_chars += chars
                except Exception as first:
                    try:
                        batch_result, chars = self.analyzer.analyze(batch)
                        batch_results.append(batch_result)
                        prompt_chars += chars
                    except Exception as second:
                        errors.append(f"lote {offset // batch_size + 1}: {type(second).__name__}: {second} (primer intento: {type(first).__name__})")
            if batch_results:
                rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
                result = {
                    "summary": " ".join(item["summary"] for item in batch_results),
                    "overall_risk": max((item["overall_risk"] for item in batch_results), key=rank.get),
                    "incidents": [incident for item in batch_results for incident in item["incidents"]],
                }
            error = "; ".join(errors) or None
            duration_ms = int((time.perf_counter() - begin) * 1000)
            self.repository.save_llm_analysis(run_id, self.clock.now_iso(), self.analyzer.model,
                                              [int(a["id"]) for a in alerts], prompt_chars, result, error, duration_ms)
        status = "partial" if error else "ok"
        self.repository.finish_run(run_id, self.clock.now_iso(), status, {
            "rules": {"status": "ok", "candidates": len(candidates), "inserted": len(inserted), "learning_baseline": learning},
            "llm": {"status": "error" if error else "ok", "error": error},
        })
        return {"run_id": run_id, "status": status, "candidates": len(candidates), "learning": learning,
                "new_alerts": len(inserted), "llm_alerts": len(alerts), "llm_error": error}
