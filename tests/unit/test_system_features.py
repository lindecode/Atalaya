from __future__ import annotations

import subprocess

import pytest

from infrastructure.windows import system_features as system


def test_interval_from_task_scheduler_durations():
    assert system._interval_minutes("PT5M") == 5
    assert system._interval_minutes("PT1H30M") == 90
    assert system._interval_minutes("") is None and system._interval_minutes("P1D") is None


def test_task_status_reads_the_real_task(monkeypatch):
    monkeypatch.setattr(system, "is_windows", lambda: True)
    answer = ('{"state":"Ready","next":"2026-10-09T18:05:00","last":"2026-10-09T18:00:00","result":0,'
              '"interval":"PT5M","execute":"C:\\\\Atalaya\\\\runtime\\\\pythonw.exe"}')
    monkeypatch.setattr(system, "_powershell", lambda args, timeout=60: subprocess.CompletedProcess(args, 0, answer, ""))
    status = system.cycle_task_status()
    assert status["enabled"] and status["minutes"] == 5 and status["windowless"] and status["state"] == "Ready"

    monkeypatch.setattr(system, "_powershell", lambda args, timeout=60: subprocess.CompletedProcess(args, 0, "{}", ""))
    assert system.cycle_task_status() == {"enabled": False}


def test_changes_use_the_installer_scripts_with_validated_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(system, "_script", lambda name, *args: calls.append((name, args)) or (True, "ok"))
    system.set_cycle_task(True, 15)
    system.set_cycle_task(False)
    system.set_startup(True)
    assert calls == [("automatizacion.ps1", ("activar", "-Minutos", "15")), ("automatizacion.ps1", ("desactivar",)),
                     ("inicio-automatico.ps1", ("activar",))]
    with pytest.raises(ValueError):
        system.set_cycle_task(True, 0)
