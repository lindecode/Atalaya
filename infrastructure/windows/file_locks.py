# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Detects processes holding open handles / locks on a file or directory using Windows Restart Manager API."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
import sys

CCH_RM_MAX_APP_NAME = 255
CCH_RM_MAX_SVC_NAME = 63
CCH_RM_SESSION_KEY = 32
ERROR_MORE_DATA = 234

RM_APP_TYPES = {
    0: ("Desconocido", "Unknown"),
    1: ("Ventana principal", "Main window"),
    2: ("Ventana secundaria", "Secondary window"),
    3: ("Servicio de Windows", "Windows service"),
    4: ("Explorador de Windows", "Windows Explorer"),
    5: ("Consola / Terminal", "Console / Terminal"),
    1000: ("Proceso crítico", "Critical system process"),
}


class RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [
        ("dwProcessId", wintypes.DWORD),
        ("ProcessStartTime", wintypes.FILETIME),
    ]


class RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [
        ("Process", RM_UNIQUE_PROCESS),
        ("strAppName", wintypes.WCHAR * (CCH_RM_MAX_APP_NAME + 1)),
        ("strServiceShortName", wintypes.WCHAR * (CCH_RM_MAX_SVC_NAME + 1)),
        ("ApplicationType", wintypes.DWORD),
        ("AppStatus", wintypes.ULONG),
        ("TSSessionId", wintypes.DWORD),
        ("bRestartable", wintypes.BOOL),
    ]


def inspect_file_locks(path: str | Path) -> list[dict]:
    """Returns a list of processes currently locking or accessing `path` using the native Windows Restart Manager."""
    target = Path(path).resolve()
    if sys.platform != "win32":
        return []

    rstrtmgr = getattr(ctypes.windll, "rstrtmgr", None)
    if not rstrtmgr:
        return []

    session_handle = wintypes.DWORD()
    session_key = (wintypes.WCHAR * (CCH_RM_SESSION_KEY + 1))()

    res = rstrtmgr.RmStartSession(ctypes.byref(session_handle), 0, session_key)
    if res != 0:
        return []

    try:
        path_str = str(target)
        file_arr = (wintypes.LPCWSTR * 1)(path_str)
        res = rstrtmgr.RmRegisterResources(session_handle, 1, file_arr, 0, None, 0, None)
        if res != 0:
            return []

        n_proc_needed = wintypes.UINT(0)
        n_proc = wintypes.UINT(0)
        reboot_reasons = wintypes.DWORD()

        res = rstrtmgr.RmGetList(
            session_handle,
            ctypes.byref(n_proc_needed),
            ctypes.byref(n_proc),
            None,
            ctypes.byref(reboot_reasons),
        )

        if n_proc_needed.value == 0:
            return []

        if res != 0 and res != ERROR_MORE_DATA:
            return []

        n_proc.value = n_proc_needed.value
        proc_info_arr = (RM_PROCESS_INFO * n_proc.value)()

        res = rstrtmgr.RmGetList(
            session_handle,
            ctypes.byref(n_proc_needed),
            ctypes.byref(n_proc),
            proc_info_arr,
            ctypes.byref(reboot_reasons),
        )
        if res != 0:
            return []

        import psutil

        results: list[dict] = []
        for i in range(n_proc.value):
            item = proc_info_arr[i]
            pid = int(item.Process.dwProcessId)
            app_name = str(item.strAppName) or "Desconocido"
            service = str(item.strServiceShortName) or None
            app_type_es, app_type_en = RM_APP_TYPES.get(item.ApplicationType, ("Desconocido", "Unknown"))

            exe_path: str | None = None
            user: str | None = None
            cmdline: str | None = None
            started: str | None = None

            try:
                proc = psutil.Process(pid)
                exe_path = proc.exe()
                user = proc.username()
                cmdline = " ".join(proc.cmdline())
                started = datetime.fromtimestamp(proc.create_time(), timezone.utc).isoformat()
                if not app_name or app_name == "Desconocido":
                    app_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            results.append({
                "pid": pid,
                "name": app_name,
                "path": exe_path,
                "service": service,
                "user": user,
                "app_type": app_type_es,
                "app_type_en": app_type_en,
                "command": cmdline,
                "started": started,
            })
        return results
    finally:
        rstrtmgr.RmEndSession(session_handle)


def terminate_lock_process(pid: int, force: bool = False) -> tuple[bool, str]:
    """Terminates a process locking a file."""
    if pid <= 4:
        return False, "No se puede finalizar un proceso crítico del sistema (PID <= 4)."
    import psutil
    try:
        proc = psutil.Process(pid)
        if force:
            proc.kill()
        else:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                proc.kill()
        return True, f"Proceso {pid} ({proc.name()}) finalizado."
    except psutil.NoSuchProcess:
        return True, f"El proceso {pid} ya no existe."
    except psutil.AccessDenied:
        return False, f"Acceso denegado al intentar finalizar el proceso {pid}. Se requieren privilegios de administrador."
    except Exception as exc:
        return False, f"Error al finalizar el proceso {pid}: {exc}"

