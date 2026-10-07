"""Atalaya in its own window (WebView2) instead of a browser tab.

The panel is still the local Streamlit server on 127.0.0.1; this only hosts it in a native window with the
Atalaya icon in the taskbar. Closing the window hides it to the tray (Atalaya keeps running); "Salir" in the
tray menu really quits. Without the WebView2 runtime or pywebview, Atalaya falls back to the browser.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
from typing import Callable

from infrastructure.windows.webview2 import webview2_version
from shared.about import APP_NAME, ASSETS_DIR, DISPLAY_NAME

log = logging.getLogger("atalaya.desktop")

SHOW_EVENT = "Local\\AtalayaShowWindow"
APP_USER_MODEL_ID = "LindeCode.Atalaya"
ICON_ICO = ASSETS_DIR / "icon.ico"

# Static splash while the panel starts (no collected data in it)
SPLASH = """<!doctype html><html><head><meta charset="utf-8"><title>Atalaya by LindeCode</title><style>
html,body{height:100%;margin:0;background:#13171F;color:#E6E9EC;font-family:Segoe UI,sans-serif}
body{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:14px}
.ring{width:42px;height:42px;border:4px solid #2A313C;border-top-color:#6BC043;border-radius:50%;animation:s 1s linear infinite}
@keyframes s{to{transform:rotate(360deg)}} h1{font-weight:600;font-size:22px;margin:0} h1 small{font-size:12px;color:#6BC043} p{margin:0;opacity:.7}
</style></head><body><div class="ring"></div><h1>Atalaya <small>by LindeCode</small></h1><p>Arrancando el panel local…</p></body></html>"""


def available() -> bool:
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return webview2_version() is not None


def set_app_user_model_id() -> None:
    """Own taskbar identity: Atalaya groups and shows its icon instead of Python's."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            log.exception("AppUserModelID")


def set_window_icon(title: str = DISPLAY_NAME) -> None:
    """WM_SETICON on the window found by title (thread-safe, unlike touching the WinForms form)."""
    if sys.platform != "win32" or not ICON_ICO.exists():
        return
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return
    for size, which in ((16, 0), (32, 1)):  # ICON_SMALL, ICON_BIG
        handle = user32.LoadImageW(None, str(ICON_ICO), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        if handle:
            user32.SendMessageW(hwnd, 0x0080, which, handle)  # WM_SETICON


class ShowRequests:
    """A second launch of Atalaya asks the running one to show its window (named event, no ports)."""

    def __init__(self, name: str = SHOW_EVENT):
        self.name = name
        self.handle = None

    def listen(self, on_request: Callable[[], None]) -> None:
        if sys.platform != "win32":
            return
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateEventW.restype = ctypes.c_void_p
        self.handle = kernel32.CreateEventW(None, False, False, self.name)

        def loop() -> None:
            while True:
                if kernel32.WaitForSingleObject(ctypes.c_void_p(self.handle), 1000) == 0:  # WAIT_OBJECT_0
                    try:
                        on_request()
                    except Exception:
                        log.exception("show request")

        threading.Thread(target=loop, daemon=True, name="show-requests").start()

    def signal(self) -> bool:
        """True if a running Atalaya received the request."""
        if sys.platform != "win32":
            return False
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenEventW.restype = ctypes.c_void_p
        handle = kernel32.OpenEventW(0x0002, False, self.name)  # EVENT_MODIFY_STATE
        if not handle:
            return False
        kernel32.SetEvent(ctypes.c_void_p(handle))
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return True


class AppWindow:
    """The Atalaya window. Closing hides it; quit() closes it for real and ends the GUI loop."""

    def __init__(self, webview_module, storage_path: str, start_hidden: bool,
                 on_first_hide: Callable[[], None] = lambda: None):
        self.webview = webview_module
        self.storage_path = storage_path
        self.on_first_hide = on_first_hide
        self.allow_close = False
        self.hidden_once = False
        self.loaded_url: str | None = None
        self.webview.settings["ALLOW_DOWNLOADS"] = True                 # CSV and report downloads
        self.webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # e.g. the Ollama download page
        self.window = self.webview.create_window(
            DISPLAY_NAME, html=SPLASH, width=1400, height=900, min_size=(1000, 650), hidden=start_hidden,
            text_select=True, zoomable=True, background_color="#13171F",
        )
        self.window.events.closing += self._on_closing
        self.window.events.shown += lambda *args: set_window_icon()

    def _on_closing(self, *args) -> bool:
        if self.allow_close:
            return True
        self.window.hide()
        if not self.hidden_once:
            self.hidden_once = True
            self.on_first_hide()
        return False  # cancel: Atalaya stays in the tray

    def preload(self, url: str) -> None:
        if url != self.loaded_url:
            self.window.load_url(url)
            self.loaded_url = url

    def show(self, url: str | None = None) -> None:
        if url:
            self.preload(url)
        self.window.show()
        self.window.restore()

    def run(self) -> None:
        """Blocks the main thread until quit()."""
        self.webview.start(gui="edgechromium", private_mode=False, storage_path=self.storage_path)

    def quit(self) -> None:
        self.allow_close = True
        self.window.destroy()
