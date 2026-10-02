"""Atalaya in the Windows notification area (next to the clock).

`main.py tray` runs without a console window (pythonw). It owns the panel (`main.py gui`) and, optionally,
the file monitor (`main.py watch`) as hidden child processes, so closing the browser tab does not stop
Atalaya: the icon shows it is still running in the background and its menu opens the panel, toggles the
monitor, collects on demand or quits everything. Severe alerts raise a Windows notification and a red dot.

Only one tray runs per user session; launching it again just opens the panel.
"""
from __future__ import annotations

import ctypes
import logging
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable

from settings import PROJECT_DIR, Settings, data_home
from shared.about import APP_NAME, ICON_PATH

GUI_PORT = 8501
OLLAMA_PORT = 11434
GUI_URL = f"http://127.0.0.1:{GUI_PORT}"
POLL_SECONDS = 60
MUTEX_NAME = "Local\\AtalayaTray"
log = logging.getLogger("atalaya.tray")


def port_open(port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def console_python() -> str:
    """python.exe next to the current interpreter: children need real stdout/stderr even if the tray is pythonw."""
    candidate = Path(sys.executable).with_name("python.exe")
    return str(candidate) if candidate.exists() else sys.executable


class ProcessManager:
    """Hidden child processes (panel, monitor) with their output in %LOCALAPPDATA%\\Atalaya\\logs."""

    def __init__(self, project_dir: Path, logs_dir: Path, popen: Callable = subprocess.Popen):
        self.project_dir, self.logs_dir, self.popen = project_dir, logs_dir, popen
        self.children: dict[str, object] = {}
        self.outputs: dict[str, object] = {}

    def running(self, name: str) -> bool:
        child = self.children.get(name)
        return child is not None and child.poll() is None

    def start(self, name: str, *args: str) -> None:
        if self.running(name):
            return
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.logs_dir / f"{name}.log"
        if log_file.exists() and log_file.stat().st_size > 5 * 1024 * 1024:
            log_file.unlink()
        output = open(log_file, "ab")
        self.outputs[name] = output
        self.children[name] = self.popen(
            [console_python(), "main.py", *args], cwd=self.project_dir, stdout=output, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def stop(self, name: str) -> None:
        child = self.children.pop(name, None)
        output = self.outputs.pop(name, None)
        if output is not None:
            output.close()
        if child is None or child.poll() is not None:
            return
        try:  # `main.py gui` starts streamlit as its own child: stop the whole tree
            import psutil
            parent = psutil.Process(child.pid)
            for process in parent.children(recursive=True) + [parent]:
                process.kill()
        except Exception:
            child.kill()

    def stop_all(self) -> None:
        for name in list(self.children):
            self.stop(name)


class AlertWatcher:
    """Remembers open critical/high alerts and reports only the ones that appeared since the last look."""

    def __init__(self, read_counts: Callable[[], dict[str, int]]):
        self.read_counts = read_counts
        self.last: int | None = None
        self.open_severe = 0

    def poll(self) -> int:
        counts = self.read_counts()
        self.open_severe = counts.get("critical", 0) + counts.get("high", 0)
        new = 0 if self.last is None else max(self.open_severe - self.last, 0)
        self.last = self.open_severe
        return new


class TrayController:
    def __init__(self, settings: Settings, processes: ProcessManager, alerts: AlertWatcher,
                 notify: Callable[[str, str], None], open_url: Callable[[str], object] = webbrowser.open,
                 gui_ready: Callable[[], bool] = lambda: port_open(GUI_PORT)):
        self.settings, self.processes, self.alerts = settings, processes, alerts
        self.notify, self.open_url, self.gui_ready = notify, open_url, gui_ready
        self.collecting = False

    # --- status -----------------------------------------------------------------------------------
    def status_text(self) -> str:
        gui = self.processes.running("gui") or self.gui_ready()
        parts = ["panel activo" if gui else "panel detenido",
                 "monitor activo" if self.processes.running("watch") else "monitor apagado"]
        if self.collecting:
            parts.append("recolectando…")
        if self.alerts.open_severe:
            parts.append(f"{self.alerts.open_severe} alerta(s) grave(s)")
        return f"{APP_NAME} en segundo plano · " + " · ".join(parts)

    # --- actions ----------------------------------------------------------------------------------
    def ensure_gui(self) -> None:
        if not self.processes.running("gui") and not self.gui_ready():
            self.processes.start("gui", "gui")

    def open_panel(self, page: str = "") -> None:
        self.ensure_gui()
        threading.Thread(target=self._open_when_ready, args=(page,), daemon=True).start()

    def _open_when_ready(self, page: str, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.gui_ready():
                self.open_url(f"{GUI_URL}/{page}" if page else GUI_URL)
                return
            time.sleep(0.5)
        self.notify(APP_NAME, "El panel no arrancó. Revise Primeros pasos o el registro en %LOCALAPPDATA%\\Atalaya\\logs.")

    def toggle_monitor(self) -> None:
        if self.processes.running("watch"):
            self.processes.stop("watch")
            self.notify(APP_NAME, "Monitor de archivos apagado.")
        else:
            self.processes.start("watch", "watch")
            self.notify(APP_NAME, "Monitor de archivos activo: vigila cambios masivos y posibles notas de rescate.")

    def collect_now(self) -> None:
        if self.collecting:
            return
        self.collecting = True
        threading.Thread(target=self._collect, daemon=True).start()

    def _collect(self) -> None:
        from bootstrap import build_analyze_service, build_collect_service
        try:
            build_collect_service(self.settings).execute()
            result = build_analyze_service(self.settings).execute()
            self.notify(APP_NAME, f"Recolección y análisis terminados: {result['new_alerts']} alerta(s) nueva(s).")
        except Exception as exc:
            log.exception("collect failed")
            self.notify(APP_NAME, f"La recolección falló: {exc}")
        finally:
            self.collecting = False

    def check_alerts(self) -> None:
        try:
            new = self.alerts.poll()
        except Exception:
            log.exception("alert poll failed")
            return
        if new:
            self.notify(f"{APP_NAME}: {new} alerta(s) grave(s) nueva(s)", "Abra el panel para revisarlas (Alertas).")

    def quit(self) -> None:
        self.processes.stop_all()


def start_ollama_if_needed() -> None:
    if port_open(OLLAMA_PORT):
        return
    from application.doctor import find_ollama
    exe = find_ollama()
    if not exe:
        return
    app = Path(exe).with_name("ollama app.exe")
    command = [str(app)] if app.exists() else [exe, "serve"]
    subprocess.Popen(command, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)


def tray_image(alert: bool = False):
    """Atalaya icon; with a red dot when severe alerts are open."""
    from PIL import Image, ImageDraw
    image = Image.open(ICON_PATH).convert("RGBA").resize((64, 64)) if ICON_PATH.exists() else None
    if image is None:  # fallback: plain shield-coloured square
        image = Image.new("RGBA", (64, 64), (56, 189, 248, 255))
    if alert:
        image = image.copy()
        draw = ImageDraw.Draw(image)
        draw.ellipse((38, 38, 63, 63), fill=(239, 68, 68, 255), outline=(255, 255, 255, 255), width=3)
    return image


def _single_instance() -> object | None:
    """Named mutex per user session; None when another tray already holds it."""
    if sys.platform != "win32":
        return object()
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def run_tray(open_browser: bool = True, monitor: bool = False) -> int:
    logs = data_home() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=logs / "tray.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if _single_instance() is None:  # already in the tray: just show the panel
        if open_browser:
            webbrowser.open(GUI_URL)
        return 0

    import pystray
    from infrastructure.sqlite.queries import SQLiteQueryRepository
    from infrastructure.sqlite.repositories import SQLiteRepository

    settings = Settings()
    SQLiteRepository(settings).initialize()
    icon = pystray.Icon("Atalaya", tray_image(), APP_NAME)

    def notify(title: str, message: str) -> None:
        try:
            icon.notify(message[:250], title[:60])
        except Exception:
            log.exception("notify failed")

    controller = TrayController(settings, ProcessManager(PROJECT_DIR, logs),
                                AlertWatcher(SQLiteQueryRepository(settings).open_alerts_by_severity), notify)

    def refresh() -> None:
        icon.title = controller.status_text()[:127]           # Windows tooltips are limited to 128 chars
        icon.icon = tray_image(alert=controller.alerts.open_severe > 0)
        icon.update_menu()

    def background(_icon) -> None:
        _icon.visible = True
        start_ollama_if_needed()
        controller.ensure_gui()
        if monitor:
            controller.processes.start("watch", "watch")
        if open_browser:
            controller.open_panel()
        notify(APP_NAME, "Atalaya sigue en segundo plano. Use este icono junto al reloj para abrir el panel o salir.")
        while True:
            controller.check_alerts()
            refresh()
            for _ in range(POLL_SECONDS):
                time.sleep(1)
                if not _icon.visible:
                    return

    def action(function):
        def handler(_icon, _item):
            function()
            refresh()
        return handler

    def quit_all(_icon, _item) -> None:
        controller.quit()
        _icon.visible = False
        _icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem("Abrir panel", action(controller.open_panel), default=True),
        pystray.MenuItem(lambda item: controller.status_text().split(" · ", 1)[1], None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Recolectar y analizar ahora", action(controller.collect_now),
                         enabled=lambda item: not controller.collecting),
        pystray.MenuItem("Monitor de archivos", action(controller.toggle_monitor),
                         checked=lambda item: controller.processes.running("watch")),
        pystray.MenuItem("Primeros pasos", action(lambda: controller.open_panel("primeros-pasos"))),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Salir de {APP_NAME}", quit_all),
    )
    log.info("tray started (browser=%s, monitor=%s)", open_browser, monitor)
    icon.run(setup=background)
    return 0
