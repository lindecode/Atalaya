from __future__ import annotations

from dataclasses import replace

import pytest

from application.automation import AutomationConfig, AutomationConfigService, CycleService
from settings import Settings


class Clock:
    def now_iso(self): return "2026-10-05T12:00:00+00:00"


class Repository:
    def __init__(self): self.preferences = {}; self.maintenance = []
    def initialize(self): pass
    def get_preference(self, key): return self.preferences.get(key)
    def set_preference(self, key, value, ts): self.preferences[key] = value
    def backup(self, destination): self.maintenance.append(("backup", destination)); return destination
    def purge(self, cutoff): self.maintenance.append(("purge", cutoff)); return {"runs": 0}


class Executable:
    def __init__(self, result): self.result = result; self.calls = []
    def execute(self, *args, **kwargs): self.calls.append((args, kwargs)); return self.result


def test_configuration_round_trip_and_validation():
    repository = Repository(); service = AutomationConfigService(repository, Clock())
    expected = AutomationConfig("standard", 48, True, False, 15, 4, 96, 60, False)
    service.save(expected)
    assert service.load() == expected
    with pytest.raises(ValueError): service.save(replace(expected, analysis_window_hours=0))


def test_cycle_skips_analysis_without_new_evidence(tmp_path):
    repository = Repository(); AutomationConfigService(repository, Clock()).save(AutomationConfig(backup_daily=False))
    collected = Executable({"inserted": 0})
    analyzed = Executable({"new_alerts": 0})
    settings = replace(Settings(), database_path=tmp_path / "atalaya.db")
    cycle = CycleService(repository, Clock(), settings, AutomationConfigService(repository, Clock()),
                         lambda profile: collected, lambda configured: analyzed)
    result = cycle.execute("quick")
    assert result["analysis_skipped"] is True
    assert analyzed.calls == []


def test_cycle_runs_rules_without_llm_when_configured(tmp_path):
    repository = Repository(); config = AutomationConfig(use_llm=False, backup_daily=False)
    AutomationConfigService(repository, Clock()).save(config)
    collected = Executable({"inserted": 2}); analyzed = Executable({"new_alerts": 1})
    settings = replace(Settings(), database_path=tmp_path / "atalaya.db")
    cycle = CycleService(repository, Clock(), settings, AutomationConfigService(repository, Clock()),
                         lambda profile: collected, lambda configured: analyzed)
    result = cycle.execute("quick")
    assert result["analysis_skipped"] is False
    assert analyzed.calls[0][1] == {"use_llm": False}


def test_deep_cycle_backs_up_before_retention(tmp_path):
    repository = Repository()
    collected = Executable({"inserted": 0}); analyzed = Executable({})
    settings = replace(Settings(), database_path=tmp_path / "atalaya.db", backup_dir=tmp_path / "backups")
    cycle = CycleService(repository, Clock(), settings, AutomationConfigService(repository, Clock()),
                         lambda profile: collected, lambda configured: analyzed)
    result = cycle.execute("deep")
    assert [operation for operation, _ in repository.maintenance] == ["backup", "purge"]
    assert result["maintenance"]["backup"].endswith(".db")
