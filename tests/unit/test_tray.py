from __future__ import annotations

from dataclasses import replace

from interfaces import tray
from settings import Settings


class FakeChild:
    def __init__(self): self.alive, self.pid = True, 4242
    def poll(self): return None if self.alive else 0
    def kill(self): self.alive = False


class FakePopen:
    def __init__(self): self.calls = []
    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return FakeChild()


def manager(tmp_path, popen=None):
    return tray.ProcessManager(tmp_path, tmp_path / "logs", popen or FakePopen())


def test_children_start_hidden_once_with_their_own_log(tmp_path):
    popen = FakePopen()
    processes = manager(tmp_path, popen)
    processes.start("gui", "gui")
    processes.start("gui", "gui")                      # already running: no second panel
    assert len(popen.calls) == 1
    command, kwargs = popen.calls[0]
    assert command[1:] == ["main.py", "gui"] and command[0].endswith("python.exe")   # console python, not pythonw
    assert kwargs["cwd"] == tmp_path and kwargs["creationflags"] == getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)
    assert (tmp_path / "logs" / "gui.log").exists()
    assert processes.running("gui")


def test_stop_kills_the_child_and_closes_its_log(tmp_path):
    processes = manager(tmp_path)
    processes.start("watch", "watch")
    child = processes.children["watch"]
    processes.stop("watch")
    assert not child.alive and not processes.running("watch") and "watch" not in processes.outputs


def test_alert_watcher_reports_only_new_severe_alerts():
    counts = iter([{"high": 2}, {"high": 2, "medium": 9}, {"high": 3, "critical": 1}, {"high": 1}])
    watcher = tray.AlertWatcher(lambda: next(counts))
    assert watcher.poll() == 0              # first look: what was already open is not "new"
    assert watcher.poll() == 0              # medium alerts do not count
    assert watcher.poll() == 2 and watcher.open_severe == 4
    assert watcher.poll() == 0 and watcher.open_severe == 1


def controller(tmp_path, gui_ready=False, counts=None):
    notes, urls = [], []
    settings = replace(Settings(), database_path=tmp_path / "t.db")
    ctrl = tray.TrayController(settings, manager(tmp_path), tray.AlertWatcher(lambda: counts or {}),
                               notify=lambda title, message: notes.append((title, message)),
                               open_url=urls.append, gui_ready=lambda: gui_ready)
    return ctrl, notes, urls


def test_status_tooltip_says_it_runs_in_the_background(tmp_path):
    ctrl, _, _ = controller(tmp_path, counts={"critical": 1})
    ctrl.alerts.poll()
    assert ctrl.status_text() == "Atalaya en segundo plano · panel detenido · monitor apagado · 1 alerta(s) grave(s)"
    ctrl.processes.start("watch", "watch")
    assert "monitor activo" in ctrl.status_text() and len(ctrl.status_text()) < 128


def test_monitor_toggle_notifies(tmp_path):
    ctrl, notes, _ = controller(tmp_path)
    ctrl.toggle_monitor()
    assert ctrl.processes.running("watch") and "activo" in notes[-1][1]
    ctrl.toggle_monitor()
    assert not ctrl.processes.running("watch") and "apagado" in notes[-1][1]


def test_open_panel_starts_the_gui_and_opens_the_page_when_ready(tmp_path):
    ctrl, _, urls = controller(tmp_path, gui_ready=True)
    ctrl._open_when_ready("primeros-pasos", timeout=1)
    assert urls == ["http://127.0.0.1:8501/primeros-pasos"]
    ctrl2, _, _ = controller(tmp_path, gui_ready=False)
    ctrl2.ensure_gui()
    assert ctrl2.processes.running("gui")


def test_new_severe_alerts_raise_a_notification(tmp_path):
    counts = iter([{"high": 0}, {"critical": 2}])
    ctrl, notes, _ = controller(tmp_path)
    ctrl.alerts = tray.AlertWatcher(lambda: next(counts))
    ctrl.check_alerts(); ctrl.check_alerts()
    assert notes and "2 alerta(s) grave(s) nueva(s)" in notes[-1][0]


def test_quit_stops_every_child(tmp_path):
    ctrl, _, _ = controller(tmp_path)
    ctrl.processes.start("gui", "gui"); ctrl.processes.start("watch", "watch")
    ctrl.quit()
    assert not ctrl.processes.running("gui") and not ctrl.processes.running("watch")


def test_icon_gets_a_red_dot_with_open_alerts():
    plain, alert = tray.tray_image(), tray.tray_image(alert=True)
    assert plain.size == alert.size == (64, 64)
    assert alert.getpixel((50, 50))[:3] == (239, 68, 68) and plain.getpixel((50, 50))[:3] != (239, 68, 68)
