"""Windows features behind the Ajustes switches: the real state, and changes made with the same scripts as the installers.

Nothing here takes free text: the task name and script paths are fixed and the interval is a validated integer.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from infrastructure.windows.common import is_windows

PROJECT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT_DIR / "start" / "lib"
TASK_NAME = "Atalaya - ciclo automatico"  # same name as start\lib\automatizacion.ps1 and desinstalar.ps1
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TASK_STATUS = (
    "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
    f"$task = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue;"
    "if (-not $task) { '{}'; exit 0 };"
    f"$info = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}';"
    "[pscustomobject]@{ state = [string]$task.State; next = $info.NextRunTime; last = $info.LastRunTime;"
    " result = $info.LastTaskResult; interval = [string]$task.Triggers[0].Repetition.Interval;"
    " execute = [string]$task.Actions[0].Execute } | ConvertTo-Json -Compress"
)


def _powershell(arguments: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", *arguments],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          check=False, creationflags=NO_WINDOW)


def _script(name: str, *arguments: str) -> tuple[bool, str]:
    try:
        completed = _powershell(["-File", str(SCRIPTS / name), *arguments])
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    output = " ".join(line.strip() for line in (completed.stdout + completed.stderr).splitlines() if line.strip())
    return completed.returncode == 0, output[:400]


def _interval_minutes(value: str) -> int | None:
    """'PT5M' / 'PT1H30M' (ISO 8601 duration from Task Scheduler) -> minutes."""
    if not value or not value.startswith("PT"):
        return None
    total, number = 0, ""
    for char in value[2:]:
        if char.isdigit():
            number += char
        else:
            total += int(number or 0) * {"H": 60, "M": 1, "S": 0}.get(char, 0)
            number = ""
    return total or None


def cycle_task_status() -> dict:
    """{'enabled', 'state', 'next', 'last', 'result', 'minutes', 'windowless'} of the scheduled cycle task."""
    if not is_windows():
        return {"enabled": False, "error": "Solo disponible en Windows"}
    try:
        completed = _powershell(["-Command", TASK_STATUS], timeout=30)
        data = json.loads(completed.stdout or "{}") if completed.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"enabled": False, "error": f"{type(exc).__name__}: {exc}"}
    if not data:
        return {"enabled": False}
    return {"enabled": True, "state": data.get("state"), "next": data.get("next"), "last": data.get("last"),
            "result": data.get("result"), "minutes": _interval_minutes(data.get("interval") or ""),
            "windowless": str(data.get("execute") or "").casefold().endswith("pythonw.exe")}


def set_cycle_task(enabled: bool, minutes: int = 5) -> tuple[bool, str]:
    minutes = int(minutes)
    if not 1 <= minutes <= 1440:
        raise ValueError("El intervalo debe estar entre 1 y 1440 minutos")
    return _script("automatizacion.ps1", "activar", "-Minutos", str(minutes)) if enabled \
        else _script("automatizacion.ps1", "desactivar")


def startup_shortcut() -> Path:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Atalaya.lnk"


def startup_enabled() -> bool:
    return startup_shortcut().exists()


def set_startup(enabled: bool) -> tuple[bool, str]:
    return _script("inicio-automatico.ps1", "activar" if enabled else "desactivar")


def file_monitor_running() -> bool:
    """A `main.py watch` process (started by the tray) is alive for this installation."""
    try:
        import psutil
    except ImportError:
        return False
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (process.info["name"] or "").casefold()
            command = " ".join(process.info["cmdline"] or [])
        except (psutil.Error, TypeError):
            continue
        if name.startswith("python") and "main.py" in command and " watch" in f" {command}":
            return True
    return False


def open_permissions_setup() -> tuple[bool, str]:
    """Runs configurar-permisos.bat elevated: Windows shows its own UAC prompt."""
    script = PROJECT_DIR / "start" / "configurar-permisos.bat"
    command = f"Start-Process -FilePath '{script}' -Verb RunAs"
    if "'" in str(script):
        return False, "La ruta de instalación contiene comillas simples; ejecute configurar-permisos.bat a mano."
    try:
        completed = _powershell(["-Command", command], timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return completed.returncode == 0, (completed.stderr or "").strip()[:300]
