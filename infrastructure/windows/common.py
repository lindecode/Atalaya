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


class WindowsSystemInfo:
    def is_admin(self) -> bool:
        return is_admin()
