from __future__ import annotations

import sys
import uuid
from dataclasses import replace

import pytest

from interfaces import desktop, tray
from infrastructure.windows.webview2 import webview2_version
from settings import Settings


class Event:
    def __init__(self): self.handlers = []
    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self
    def fire(self):
        return [handler() for handler in self.handlers]


class FakeWindow:
    def __init__(self, **kwargs):
        self.kwargs, self.visible, self.urls, self.destroyed = kwargs, not kwargs["hidden"], [], False
        self.events = type("Events", (), {"closing": Event(), "shown": Event()})()
    def hide(self): self.visible = False
    def show(self): self.visible = True
    def restore(self): pass
    def load_url(self, url): self.urls.append(url)
    def destroy(self): self.destroyed = True


class FakeWebview:
    def __init__(self): self.settings, self.started = {"ALLOW_DOWNLOADS": False}, None
    def create_window(self, title, **kwargs):
        self.window = FakeWindow(title=title, **kwargs)
        return self.window
    def start(self, **kwargs): self.started = kwargs


def app_window(start_hidden=False):
    hides = []
    webview = FakeWebview()
    window = desktop.AppWindow(webview, "C:/data/webview", start_hidden, on_first_hide=lambda: hides.append(1))
    return window, webview, hides


def test_window_is_configured_for_an_app_not_a_browser():
    window, webview, _ = app_window()
    kwargs = webview.window.kwargs
    assert kwargs["title"] == "Atalaya" and "Arrancando" in kwargs["html"] and kwargs["text_select"]
    assert webview.settings["ALLOW_DOWNLOADS"] and webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"]
    window.run()
    assert webview.started == {"gui": "edgechromium", "private_mode": False, "storage_path": "C:/data/webview"}


def test_closing_hides_to_the_tray_and_notifies_once():
    window, webview, hides = app_window()
    assert webview.window.events.closing.fire() == [False]          # close cancelled
    assert not webview.window.visible and hides == [1]
    window.show()
    webview.window.events.closing.fire()
    assert hides == [1]                                              # only the first time


def test_quit_really_closes():
    window, webview, _ = app_window()
    window.quit()
    assert webview.window.destroyed and webview.window.events.closing.fire() == [True]


def test_show_loads_a_page_once_and_preload_keeps_it_hidden():
    window, webview, _ = app_window(start_hidden=True)
    window.preload("http://127.0.0.1:8501")
    assert not webview.window.visible and webview.window.urls == ["http://127.0.0.1:8501"]
    window.show("http://127.0.0.1:8501")                             # same page: no reload, user keeps their place
    assert webview.window.visible and webview.window.urls == ["http://127.0.0.1:8501"]
    window.show("http://127.0.0.1:8501/primeros-pasos")
    assert webview.window.urls[-1].endswith("/primeros-pasos")


@pytest.mark.skipif(sys.platform != "win32", reason="registro de Windows")
def test_webview2_detection_per_machine_or_per_user():
    import winreg
    assert webview2_version(lambda hive, path: None) is None
    assert webview2_version(lambda hive, path: "0.0.0.0") is None    # placeholder left by uninstalls
    per_user = lambda hive, path: "154.0.1" if hive == winreg.HKEY_CURRENT_USER else None
    assert webview2_version(per_user) == "154.0.1"


@pytest.mark.skipif(sys.platform != "win32", reason="eventos con nombre de Windows")
def test_second_launch_asks_the_running_one_to_show_itself():
    import threading
    name = f"Local\\AtalayaTest-{uuid.uuid4().hex}"
    assert desktop.ShowRequests(name).signal() is False             # nobody running: caller opens it itself
    shown = threading.Event()
    desktop.ShowRequests(name).listen(shown.set)
    assert desktop.ShowRequests(name).signal() is True
    assert shown.wait(3)


def test_controller_preloads_the_window_and_can_still_use_the_browser(tmp_path):
    preloaded, browsed, shown = [], [], []
    settings = replace(Settings(), database_path=tmp_path / "t.db")
    controller = tray.TrayController(settings, tray.ProcessManager(tmp_path, tmp_path / "logs", lambda *a, **k: None),
                                     tray.AlertWatcher(dict), notify=lambda *a: None, open_url=shown.append,
                                     gui_ready=lambda: True, preload_url=preloaded.append, browser=browsed.append)
    controller._open_when_ready("", controller.preload_url, timeout=1)
    controller._open_when_ready("alertas", controller.browser, timeout=1)
    assert preloaded == ["http://127.0.0.1:8501"] and browsed == ["http://127.0.0.1:8501/alertas"] and shown == []
