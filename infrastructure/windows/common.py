# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
