from __future__ import annotations

import json
import subprocess
from pathlib import Path

from domain.models import CollectionRequest, CollectionResult, PersistenceItem
from infrastructure.windows.common import is_windows
from settings import Settings


class WindowsPersistenceCollector:
    name = "windows_persistence"

    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def _registry_items(now: str) -> tuple[list[PersistenceItem], list[str]]:
        import winreg

        items: list[PersistenceItem] = []
        warnings: list[str] = []
        key_path = r"Software\Microsoft\Windows\CurrentVersion"
        for hive, hive_name in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
            for suffix in ("Run", "RunOnce"):
                location = f"{hive_name}\\{key_path}\\{suffix}"
                try:
                    with winreg.OpenKey(hive, f"{key_path}\\{suffix}") as key:
                        for index in range(winreg.QueryInfoKey(key)[1]):
                            name, command, _ = winreg.EnumValue(key, index)
                            items.append(PersistenceItem(now, now, "run_key", location, name, str(command)))
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    warnings.append(f"{location}: {exc}")
        return items, warnings

    @staticmethod
    def _powershell_json(script: str) -> list[dict[str, object]]:
        encoded_script = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);" + script
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", encoded_script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode:
            detail = completed.stderr.strip() or f"PowerShell terminó con código {completed.returncode}"
            raise RuntimeError(detail)
        if not completed.stdout.strip():
            return []
        parsed = json.loads(completed.stdout)
        return parsed if isinstance(parsed, list) else [parsed]

    def collect(self, request: CollectionRequest) -> CollectionResult:
        if not is_windows():
            return CollectionResult(self.name, "persistence_items", (), "skipped", ("Solo disponible en Windows",))
        items, warnings = self._registry_items(request.now)

        startup = next((path for path in self.settings.watch_dirs if path.name.casefold() == "startup"), None)
        if startup and startup.exists():
            try:
                for path in startup.iterdir():
                    if path.is_file():
                        items.append(PersistenceItem(request.now, request.now, "startup_folder", str(startup), path.name, str(path)))
            except OSError as exc:
                warnings.append(f"Startup: {exc}")

        task_script = (
            "Get-ScheduledTask | ForEach-Object { [pscustomobject]@{"
            "Location=$_.TaskPath; Name=$_.TaskName; Command=(($_.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) -join '; ')"
            "} } | ConvertTo-Json -Compress -Depth 4"
        )
        service_script = (
            "Get-CimInstance Win32_Service | Select-Object @{n='Location';e={$_.Name}},"
            "@{n='Name';e={$_.DisplayName}},@{n='Command';e={$_.PathName}} | ConvertTo-Json -Compress"
        )
        for kind, script in (("scheduled_task", task_script), ("service", service_script)):
            try:
                for row in self._powershell_json(script):
                    items.append(PersistenceItem(
                        request.now, request.now, kind, str(row.get("Location") or ""),
                        str(row.get("Name") or ""), str(row.get("Command") or "") or None,
                    ))
            except (subprocess.SubprocessError, json.JSONDecodeError, OSError, RuntimeError) as exc:
                warnings.append(f"{kind}: {exc}")

        return CollectionResult(
            self.name, "persistence_items", tuple(items), "partial" if warnings else "ok", tuple(warnings)
        )
