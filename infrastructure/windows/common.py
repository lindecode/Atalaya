from __future__ import annotations

import ctypes
import os


def is_windows() -> bool:
    return os.name == "nt"


def is_admin() -> bool:
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def pid_alive(pid: int) -> bool:
    """Whether a process with this PID exists; used to reclaim lock files left by a crashed cycle."""
    import psutil
    return psutil.pid_exists(pid)


class WindowsSystemInfo:
    def is_admin(self) -> bool:
        return is_admin()
