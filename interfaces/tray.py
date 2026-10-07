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
import json
from urllib.request import ProxyHandler, Request, build_opener
from pathlib import Path
from typing import Callable

from settings import PROJECT_DIR, Settings, data_home
from shared.about import APP_NAME, ICON_PATH
from interfaces.gui_instance import DEFAULT_PORT, available_port, new_token, read_valid_instance

GUI_PORT = DEFAULT_PORT
OLLAMA_PORT = 11434
POLL_SECONDS = 60
MUTEX_NAME = "Local\\AtalayaTray"
log = logging.getLogger("atalaya.tray")


def port_open(port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def ollama_ready(timeout: float = 1.0) -> bool:
    """Validate the local service as Ollama instead of trusting an occupied TCP port."""
    try:
        response = build_opener(ProxyHandler({})).open(
            Request(f"http://127.0.0.1:{OLLAMA_PORT}/api/version", headers={"Accept": "application/json"}),
            timeout=timeout,
        )
        payload = json.loads(response.read(4096).decode("utf-8"))
        return response.status == 200 and isinstance(payload.get("version"), str)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
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

    def adopt(self, name: str, child) -> None:
        """Track a securely constructed external child so Quit stops it too."""
        if child is not None:
            self.children[name] = child

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
                 gui_ready: Callable[[], bool] | None = None,
                 preload_url: Callable[[str], object] | None = None, browser: Callable[[str], object] = webbrowser.open):
        self.settings, self.processes, self.alerts = settings, processes, alerts
        self.notify, self.open_url = notify, open_url
        self.preload_url, self.browser = preload_url, browser
        self.collecting = False
        self.gui_port = GUI_PORT
        self.gui_token = new_token()
        self.instance_path = data_home() / "gui-instance.json"
        self.gui_ready = gui_ready or self._registered_gui_ready

    @property
    def gui_url(self) -> str:
        return f"http://127.0.0.1:{self.gui_port}"

    def _registered_gui_ready(self) -> bool:
        instance = read_valid_instance(self.instance_path, self.gui_token)
        return instance is not None and instance.port == self.gui_port

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
            self.gui_port = available_port()
            self.gui_token = new_token()
            self.processes.start("gui", "gui", "--port", str(self.gui_port), "--instance-token", self.gui_token)

    def open_panel(self, page: str = "") -> None:
        self.ensure_gui()
        threading.Thread(target=self._open_when_ready, args=(page,), daemon=True).start()

    def open_panel_later(self) -> None:
        """Load the panel into the (hidden) window without showing it."""
        if self.preload_url:
            self.ensure_gui()
            threading.Thread(target=self._open_when_ready, args=("", self.preload_url), daemon=True).start()

    def open_in_browser(self, page: str = "") -> None:
        self.ensure_gui()
        threading.Thread(target=self._open_when_ready, args=(page, self.browser), daemon=True).start()

    def _open_when_ready(self, page: str, opener: Callable[[str], object] | None = None, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.gui_ready():
                (opener or self.open_url)(f"{self.gui_url}/{page}" if page else self.gui_url)
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


def start_llm_if_needed(settings: Settings | None = None):
    settings = settings or Settings()
    from infrastructure.llm_provider import provider_name
    if provider_name(settings) == "llama_cpp":
        from infrastructure.llama_cpp.runtime import start_if_needed
        try:
            return start_if_needed(settings)
        except RuntimeError:
            log.exception("llama.cpp did not start")
        return None
    if ollama_ready():
        return
    from application.doctor import find_ollama
    exe = find_ollama()
    if not exe:
        return
    app = Path(exe).with_name("ollama app.exe")
    command = [str(app)] if app.exists() else [exe, "serve"]
    subprocess.Popen(command, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    return None


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


def run_tray(open_browser: bool = True, monitor: bool = False, force_browser: bool = False) -> int:
    """Tray icon + panel. With WebView2 the panel opens in Atalaya's own window; otherwise in the browser.

    `open_browser=False` starts hidden (autostart); the name is kept for the CLI's --no-browser flag.
    """
    from interfaces import desktop

    logs = data_home() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=logs / "tray.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    requests = desktop.ShowRequests()
    if _single_instance() is None:  # already running: ask it to show itself
        if open_browser and not requests.signal():
            instance = read_valid_instance(data_home() / "gui-instance.json")
            if instance:
                webbrowser.open(instance.url)
        return 0

    import pystray
    from infrastructure.sqlite.queries import SQLiteQueryRepository
    from infrastructure.sqlite.repositories import SQLiteRepository

    use_window = not force_browser and desktop.available()
    settings = Settings()
    SQLiteRepository(settings).initialize()
    icon = pystray.Icon("Atalaya", tray_image(), APP_NAME)

    def notify(title: str, message: str) -> None:
        try:
            icon.notify(message[:250], title[:60])
        except Exception:
            log.exception("notify failed")

    window = None
    if use_window:
        import webview
        desktop.set_app_user_model_id()
        window = desktop.AppWindow(
            webview, str(data_home() / "webview"), start_hidden=not open_browser,
            on_first_hide=lambda: notify(APP_NAME, "Atalaya sigue en segundo plano. Ábralo desde este icono junto al "
                                                   "reloj; para cerrarlo del todo: Salir de Atalaya."))
    controller = TrayController(settings, ProcessManager(PROJECT_DIR, logs),
                                AlertWatcher(SQLiteQueryRepository(settings).open_alerts_by_severity), notify,
                                open_url=window.show if window else webbrowser.open,
                                preload_url=window.preload if window else None)

    def refresh() -> None:
        icon.title = controller.status_text()[:127]           # Windows tooltips are limited to 128 chars
        icon.icon = tray_image(alert=controller.alerts.open_severe > 0)
        icon.update_menu()

    def background(_icon) -> None:
        _icon.visible = True
        controller.processes.adopt("llama_cpp", start_llm_if_needed(settings))
        controller.ensure_gui()
        if monitor:
            controller.processes.start("watch", "watch")
        if open_browser:
            controller.open_panel()
        elif window:
            controller.open_panel_later()  # hidden window gets the panel loaded, ready for the first "Abrir"
        if not open_browser:
            notify(APP_NAME, "Atalaya está en segundo plano. Use este icono junto al reloj para abrirlo o salir.")
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
        if window:
            window.quit()          # ends window.run() on the main thread, which then stops the icon
        else:
            _icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem("Abrir Atalaya", action(controller.open_panel), default=True),
        pystray.MenuItem(lambda item: controller.status_text().split(" · ", 1)[1], None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Recolectar y analizar ahora", action(controller.collect_now),
                         enabled=lambda item: not controller.collecting),
        pystray.MenuItem("Monitor de archivos", action(controller.toggle_monitor),
                         checked=lambda item: controller.processes.running("watch")),
        pystray.MenuItem("Primeros pasos", action(lambda: controller.open_panel("primeros-pasos"))),
        pystray.MenuItem("Abrir en el navegador", action(controller.open_in_browser), visible=bool(window)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Salir de {APP_NAME}", quit_all),
    )
    requests.listen(controller.open_panel)  # a second launch (menu Inicio, escritorio) shows this instance
    log.info("tray started (window=%s, open=%s, monitor=%s)", use_window, open_browser, monitor)
    if window:
        icon.run_detached(setup=background)
        window.run()               # main thread: WebView2 needs it; returns after quit()
        icon.stop()
    else:
        icon.run(setup=background)
    return 0
