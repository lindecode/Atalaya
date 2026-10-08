from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable


PREFERENCE_KEY = "automation_config_v1"


@dataclass(frozen=True, slots=True)
class AutomationConfig:
    profile: str = "quick"
    analysis_window_hours: int = 24
    automatic_analysis: bool = True
    use_llm: bool = True
    cycle_minutes: int = 5
    standard_every_cycles: int = 12
    deep_every_cycles: int = 288
    retention_days: int = 30
    backup_daily: bool = True

    def validated(self) -> "AutomationConfig":
        if self.profile not in {"quick", "standard", "deep"}: raise ValueError("Perfil inválido")
        if not 1 <= self.analysis_window_hours <= 24 * 30: raise ValueError("La ventana debe estar entre 1 y 720 horas")
        if not 1 <= self.cycle_minutes <= 1440: raise ValueError("El ciclo debe estar entre 1 y 1440 minutos")
        if not 1 <= self.standard_every_cycles <= 10_000: raise ValueError("Frecuencia standard inválida")
        if not 1 <= self.deep_every_cycles <= 100_000: raise ValueError("Frecuencia deep inválida")
        if not 1 <= self.retention_days <= 3650: raise ValueError("Retención inválida")
        return self


class AutomationConfigService:
    def __init__(self, repository, clock): self.repository, self.clock = repository, clock

    def load(self) -> AutomationConfig:
        self.repository.initialize()
        raw = self.repository.get_preference(PREFERENCE_KEY)
        if not raw: return AutomationConfig()
        try:
            values = json.loads(raw)
            allowed = set(AutomationConfig.__dataclass_fields__)
            return AutomationConfig(**{key: value for key, value in values.items() if key in allowed}).validated()
        except (TypeError, ValueError, json.JSONDecodeError):
            return AutomationConfig()

    def save(self, config: AutomationConfig) -> AutomationConfig:
        config.validated(); self.repository.initialize()
        self.repository.set_preference(PREFERENCE_KEY, json.dumps(asdict(config)), self.clock.now_iso())
        return config


class CycleService:
    def __init__(self, repository, clock, settings, config_service, collect_factory, analyze_factory,
                 pid_alive: Callable[[int], bool] = lambda pid: True,
                 summary_step: Callable[[int], dict | None] | None = None):
        self.repository, self.clock, self.settings = repository, clock, settings
        self.config_service = config_service
        self.collect_factory, self.analyze_factory = collect_factory, analyze_factory
        self.pid_alive = pid_alive
        self.summary_step = summary_step

    def execute(self, profile: str | None = None, force_analysis=False, use_llm: bool | None = None):
        config = self.config_service.load()
        selected = profile or self._scheduled_profile(config)
        lock = _CycleLock(self.settings.database_path.with_suffix(".cycle.lock"), self.pid_alive)
        with lock:
            collected = self.collect_factory(selected).execute()
            should_analyze = config.automatic_analysis and (force_analysis or int(collected["inserted"]) > 0)
            analyzed = None
            if should_analyze:
                effective = replace(self.settings, rule_window_hours=config.analysis_window_hours,
                                    retention_days=config.retention_days)
                analyzed = self.analyze_factory(effective).execute(
                    use_llm=config.use_llm if use_llm is None else use_llm)
            maintenance = self._maintenance(config, selected)
            summary = self._summary(config, analyzed, config.use_llm if use_llm is None else use_llm)
            self.repository.set_preference("automation_cycle_count", str(self._cycle_count() + 1), self.clock.now_iso())
            return {"profile": selected, "collected": collected, "analyzed": analyzed,
                    "analysis_skipped": not should_analyze, "maintenance": maintenance, "summary": summary}

    def _summary(self, config, analyzed, use_llm: bool) -> dict | None:
        """At most one section summary per cycle, and none when this cycle's analysis already used the LLM."""
        if not self.summary_step or not use_llm:
            return None
        if analyzed and analyzed.get("llm_alerts"):
            return {"skipped": "El LLM ya analizó alertas en este ciclo"}
        try:
            return self.summary_step(config.analysis_window_hours)
        except Exception as exc:  # a summary never breaks the cycle
            return {"error": f"{type(exc).__name__}: {exc}"}

    def _cycle_count(self):
        try: return int(self.repository.get_preference("automation_cycle_count") or 0)
        except ValueError: return 0

    def _scheduled_profile(self, config):
        count = self._cycle_count() + 1
        if count % config.deep_every_cycles == 0: return "deep"
        if count % config.standard_every_cycles == 0: return "standard"
        return config.profile

    def _maintenance(self, config, profile):
        result = {"backup": None, "purged": None}
        now = datetime.fromisoformat(self.clock.now_iso())
        today = now.date().isoformat()
        if config.backup_daily and self.repository.get_preference("automation_last_backup_date") != today:
            destination = self.settings.backup_dir / f"atalaya_{now.strftime('%Y%m%d_%H%M%S')}.db"
            result["backup"] = str(self.repository.backup(destination))
            self.repository.set_preference("automation_last_backup_date", today, self.clock.now_iso())
        if profile == "deep":
            cutoff = (now - timedelta(days=config.retention_days)).isoformat()
            result["purged"] = self.repository.purge(cutoff)
        return result


class _CycleLock:
    """Exclusive lock file holding the owner's PID; a lock left by a dead process (crash, power loss) is reclaimed."""

    def __init__(self, path: Path, pid_alive: Callable[[int], bool] = lambda pid: True,
                 busy_message: str = "Ya hay un ciclo automático en ejecución"):
        self.path, self.pid_alive, self.fd, self.busy_message = path, pid_alive, None, busy_message

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._acquire()
        except FileExistsError:
            if not self._reclaim_stale():
                raise RuntimeError(self.busy_message) from None
            try:
                self._acquire()
            except FileExistsError as exc:  # another cycle reclaimed it first
                raise RuntimeError(self.busy_message) from exc
        return self

    def _acquire(self):
        self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(self.fd, str(os.getpid()).encode("ascii"))

    def _reclaim_stale(self) -> bool:
        try:
            owner = int(self.path.read_text(encoding="ascii").strip())
        except FileNotFoundError:
            return True  # released between our attempt and the read
        except (OSError, ValueError):
            return False  # unreadable or half-written: leave it for doctor and the user
        if owner == os.getpid() or self.pid_alive(owner):
            return False
        try: self.path.unlink()
        except FileNotFoundError: pass
        return True

    def __exit__(self, *_):
        if self.fd is not None: os.close(self.fd)
        try: self.path.unlink()
        except FileNotFoundError: pass
