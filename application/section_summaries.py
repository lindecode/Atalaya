"""LLM summary per GUI section: on demand, or one section per automatic cycle so the GPU never gets all at once."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from application.automation import _CycleLock

SECTIONS = {
    "panel": "Panel de seguridad", "conexiones": "Conexiones", "accesos": "Accesos", "archivos": "Archivos",
    "persistencia": "Persistencia", "firewall": "Firewall", "procesos": "Procesos y RAM",
}
LLM_BUSY = "El LLM local está ocupado con otro resumen; inténtelo en un momento"


class SectionSummaryService:
    def __init__(self, digests, store, summarizer_factory: Callable[[], object], model: str, clock, lock_path: Path,
                 pid_alive: Callable[[int], bool] = lambda pid: True, min_interval_minutes: int = 60):
        self.digests, self.store, self.summarizer_factory = digests, store, summarizer_factory
        self.model, self.clock, self.lock_path, self.pid_alive = model, clock, lock_path, pid_alive
        self.min_interval = timedelta(minutes=min_interval_minutes)

    def _digest(self, section: str, window_hours: int) -> tuple[dict, str]:
        digest = self.digests.digest(section, window_hours, self.clock.now_iso())
        return digest, hashlib.sha256(json.dumps(digest, sort_keys=True, default=str).encode()).hexdigest()

    def summarize(self, section: str, window_hours: int, trigger: str = "manual") -> dict:
        """Summarize one section now. Only one LLM summary runs at a time (GUI button and cycle share the lock)."""
        if section not in SECTIONS:
            raise ValueError(f"Sección desconocida: {section}")
        digest, digest_hash = self._digest(section, window_hours)
        model = self.model
        with _CycleLock(self.lock_path, self.pid_alive, busy_message=LLM_BUSY):
            try:
                summarizer = self.summarizer_factory()
                model = getattr(summarizer, "model", model)
                result, error = summarizer.summarize(SECTIONS[section], digest), None
            except Exception as exc:  # provider down, timeout, invalid JSON: keep the attempt for the queue
                result, error = None, f"{type(exc).__name__}: {exc}"[:500]
        self.store.save(section, self.clock.now_iso(), trigger, window_hours, model, digest_hash, digest,
                        result, error)
        return {"section": section, "result": result, "error": error}

    def due_section(self, window_hours: int) -> str | None:
        """The section waiting longest whose data changed since its last summary and is not summarized too recently."""
        now = datetime.fromisoformat(self.clock.now_iso())
        candidates = []
        for section in SECTIONS:
            last = self.store.latest(section)
            if last and now - datetime.fromisoformat(last["created_at"]) < self.min_interval:
                continue
            _, digest_hash = self._digest(section, window_hours)
            if last and last["digest_hash"] == digest_hash and last.get("result_json"):
                continue  # nothing new to say
            candidates.append((last["created_at"] if last else "", section))
        return min(candidates)[1] if candidates else None

    def run_next(self, window_hours: int) -> dict | None:
        """The automatic step: at most one section per call."""
        section = self.due_section(window_hours)
        return self.summarize(section, window_hours, trigger="auto") if section else None
