from __future__ import annotations

import time
from datetime import datetime, timedelta

from domain.rules import ALL_RULES
from ports.clock import Clock
from ports.llm import StructuredAnalyzer
from ports.repositories import AnalysisRepository
from ports.system import SystemInfo
from settings import Settings


RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


class AnalyzeService:
    def __init__(self, repository: AnalysisRepository, analyzer: StructuredAnalyzer, clock: Clock,
                 system_info: SystemInfo, settings: Settings, rules=ALL_RULES):
        self.repository = repository
        self.analyzer = analyzer
        self.clock = clock
        self.system_info = system_info
        self.settings = settings
        self.rules = tuple(rules)

    def execute(self, use_llm: bool = True) -> dict[str, object]:
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
        alerts = self.repository.get_new_alerts(limit=self.settings.llm_max_alerts)
        error = None
        analyzed_ids: list[int] = []
        if alerts and use_llm:
            batch_results = []
            errors = []
            prompt_chars = 0
            begin = time.perf_counter()
            batch_size = self.settings.llm_batch_size
            for offset in range(0, len(alerts), batch_size):
                batch = alerts[offset:offset + batch_size]
                try:
                    batch_result, chars, sent_ids = self._analyze_with_retry(batch)
                except RuntimeError as exc:
                    errors.append(f"lote {offset // batch_size + 1}: {exc}")
                    continue
                batch_results.append(batch_result)
                prompt_chars += chars
                analyzed_ids += sent_ids
            result = None
            if batch_results:
                result = {
                    "summary": " ".join(item["summary"] for item in batch_results),
                    "overall_risk": max((item["overall_risk"] for item in batch_results), key=RANK.get),
                    "incidents": [incident for item in batch_results for incident in item["incidents"]],
                }
            error = "; ".join(errors) or None
            duration_ms = int((time.perf_counter() - begin) * 1000)
            # Only the alerts the model actually received become 'analyzed'; failed batches stay 'new'
            self.repository.save_llm_analysis(run_id, self.clock.now_iso(), self.analyzer.model,
                                              analyzed_ids, prompt_chars, result, error, duration_ms)
        status = "partial" if error else "ok"
        self.repository.finish_run(run_id, self.clock.now_iso(), status, {
            "rules": {"status": "ok", "candidates": len(candidates), "inserted": len(inserted), "learning_baseline": learning},
            "llm": {"status": "disabled" if not use_llm else "error" if error else "ok", "model": self.analyzer.model, "error": error},
        })
        return {"run_id": run_id, "status": status, "candidates": len(candidates), "learning": learning,
                "new_alerts": len(inserted), "llm_alerts": len(analyzed_ids), "llm_model": self.analyzer.model,
                "llm_error": error}

    def _analyze_with_retry(self, batch):
        try:
            return self.analyzer.analyze(batch)
        except Exception as first:
            try:
                return self.analyzer.analyze(batch)
            except Exception as second:
                raise RuntimeError(f"{type(second).__name__}: {second} (primer intento: {type(first).__name__})") from second
