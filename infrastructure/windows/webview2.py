"""Microsoft Edge WebView2 Runtime detection (needed for Atalaya's own window)."""
from __future__ import annotations

import sys
from typing import Callable

WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"  # Microsoft Edge WebView2 Runtime


def webview2_version(read_registry: Callable[[int, str], str | None] | None = None) -> str | None:
    """Installed WebView2 runtime version (per machine or per user), or None."""
    if sys.platform != "win32":
        return None
    import winreg

    def default_read(hive: int, path: str) -> str | None:
        try:
            with winreg.OpenKey(hive, path) as key:
                return str(winreg.QueryValueEx(key, "pv")[0])
        except OSError:
            return None

    read = read_registry or default_read
    client = r"Microsoft\EdgeUpdate\Clients" + "\\" + WEBVIEW2_GUID
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node" + "\\" + client),   # per machine
                       (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE" + "\\" + client),
                       (winreg.HKEY_CURRENT_USER, r"Software" + "\\" + client)):               # per user
        version = read(hive, path)
        if version and version != "0.0.0.0":
            return version
    return None
