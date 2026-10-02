"""`atalaya doctor`: checks what Atalaya needs on this machine and says how to fix what is missing.

Used by the CLI, the GUI "Primeros pasos" page and start\\diagnostico.bat. Every probe is injectable so the
logic is tested without Ollama, the event log or the real disk.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

Status = Literal["ok", "warn", "fail", "info"]

RUNTIME_MODULES = ("psutil", "win32evtlog", "watchdog", "ollama", "streamlit", "pydantic", "pandas", "plotly", "pystray")
MIN_PYTHON = (3, 11)
MIN_FREE_GB = 2.0
OLLAMA_DOWNLOAD = "https://ollama.com/download/windows"


@dataclass(frozen=True)
class Check:
    id: str
    group: str
    title: str
    status: Status
    detail: str
    fix: str = ""


def find_ollama() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    default = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return str(default) if default.exists() else None


def _security_log_readable() -> tuple[bool, str]:
    try:
        import win32evtlog
    except ImportError:
        return False, "pywin32 no está instalado"
    try:
        win32evtlog.EvtQuery("Security", win32evtlog.EvtQueryChannelPath, "*[System[EventRecordID=1]]")
        return True, ""
    except Exception as exc:  # pywin32 raises its own error type; code 5 is access denied
        return False, str(exc)


def _sysmon_installed() -> bool:
    try:
        import win32evtlog
        win32evtlog.EvtQuery("Microsoft-Windows-Sysmon/Operational", win32evtlog.EvtQueryChannelPath, "*[System[EventRecordID=1]]")
        return True
    except Exception:
        return False


def _total_ram_gb() -> float | None:
    try:
        import psutil
        return psutil.virtual_memory().total / 1024 ** 3
    except Exception:
        return None


class DoctorService:
    def __init__(self, settings, model_service, *, find_ollama: Callable[[], str | None] = find_ollama,
                 security_readable: Callable[[], tuple[bool, str]] = _security_log_readable,
                 sysmon_installed: Callable[[], bool] = _sysmon_installed,
                 total_ram_gb: Callable[[], float | None] = _total_ram_gb,
                 module_available: Callable[[str], bool] = lambda name: importlib.util.find_spec(name) is not None,
                 disk_free_gb: Callable[[Path], float] = lambda path: shutil.disk_usage(path).free / 1024 ** 3):
        self.settings, self.models = settings, model_service
        self.find_ollama, self.security_readable, self.sysmon_installed = find_ollama, security_readable, sysmon_installed
        self.total_ram_gb, self.module_available, self.disk_free_gb = total_ram_gb, module_available, disk_free_gb

    def run(self) -> list[Check]:
        return self._python() + self._data() + self._ollama() + self._sources()

    # --- Python y dependencias ------------------------------------------------------------------
    def _python(self) -> list[Check]:
        version = ".".join(map(str, sys.version_info[:3]))
        bundled = (self.settings.project_dir / "runtime").resolve() in Path(sys.executable).resolve().parents
        origin = "incluido en Atalaya" if bundled else sys.executable
        checks = [Check("python", "Programa", "Python", "ok" if sys.version_info >= MIN_PYTHON else "fail",
                        f"{version} ({origin})", "" if sys.version_info >= MIN_PYTHON else
                        "Instale Python 3.11 o superior, o use el instalador Atalaya-Setup.exe que ya lo incluye")]
        missing = [name for name in RUNTIME_MODULES if not self.module_available(name)]
        checks.append(Check("deps", "Programa", "Dependencias", "fail" if missing else "ok",
                            f"Faltan: {', '.join(missing)}" if missing else f"{len(RUNTIME_MODULES)} paquetes disponibles",
                            "Ejecute start\\instalar.bat o reinstale Atalaya" if missing else ""))
        return checks

    # --- Datos ----------------------------------------------------------------------------------
    def _data(self) -> list[Check]:
        folder = self.settings.database_path.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".write-test"
            probe.write_text("", encoding="utf-8"); probe.unlink()
            free = self.disk_free_gb(folder)
        except OSError as exc:
            return [Check("data", "Programa", "Carpeta de datos", "fail", f"{folder}: {exc}",
                          "Compruebe permisos o defina ATALAYA_HOME con una carpeta escribible")]
        status: Status = "warn" if free < MIN_FREE_GB else "ok"
        return [Check("data", "Programa", "Carpeta de datos", status, f"{folder} · {free:.1f} GB libres",
                      "Libere espacio: los modelos y la base de datos lo necesitan" if status == "warn" else "")]

    # --- Ollama y modelos -----------------------------------------------------------------------
    def _ollama(self) -> list[Check]:
        exe = self.find_ollama()
        if not exe:
            return [Check("ollama", "LLM local", "Ollama", "warn", "No instalado: las reglas y alertas funcionan, "
                          "pero no hay explicaciones del LLM ni chat",
                          f"Instálelo con «winget install Ollama.Ollama» o desde {OLLAMA_DOWNLOAD}")]
        try:
            installed = {model["name"]: model for model in self.models.available()}
        except Exception as exc:
            return [Check("ollama", "LLM local", "Ollama", "warn", f"Instalado ({exe}) pero no responde: {exc}",
                          "Ábralo desde el menú Inicio (Ollama) o pulse Abrir panel: Atalaya lo arranca")]
        checks = [Check("ollama", "LLM local", "Ollama", "ok", f"En marcha · {len(installed)} modelo(s) instalados")]
        chat_model = self.models.current()
        chat = installed.get(chat_model) or installed.get(f"{chat_model}:latest")
        if not chat:
            checks.append(Check("model-chat", "LLM local", "Modelo de análisis y chat", "warn",
                                f"{chat_model} no está descargado", f"Descárguelo aquí o con «ollama pull {chat_model}»"))
        elif not chat["tools"]:
            checks.append(Check("model-chat", "LLM local", "Modelo de análisis y chat", "warn",
                                f"{chat_model} analiza, pero no admite herramientas: el chat no funcionará",
                                "Elija un modelo con tools en la barra lateral (p. ej. qwen3.5:4b)"))
        else:
            checks.append(Check("model-chat", "LLM local", "Modelo de análisis y chat", "ok",
                                f"{chat_model} · {chat.get('parameters') or '?'} · {chat.get('size_gb', '?')} GB"))
        embedding = self.settings.ollama_embedding_model
        has_embedding = embedding in installed or f"{embedding}:latest" in installed or embedding.removesuffix(":latest") in installed
        checks.append(Check("model-embed", "LLM local", "Modelo de embeddings (opcional)", "ok" if has_embedding else "info",
                            embedding if has_embedding else f"{embedding} no está descargado: el chat busca solo por texto",
                            "" if has_embedding else f"Descárguelo aquí o con «ollama pull {embedding}»"))
        ram = self.total_ram_gb()
        if ram is not None and ram < 8:
            checks.append(Check("ram", "LLM local", "Memoria", "warn", f"{ram:.0f} GB de RAM",
                                "Con menos de 8 GB use un modelo pequeño, p. ej. qwen3.5:0.8b"))
        return checks

    # --- Fuentes de evidencia -------------------------------------------------------------------
    def _sources(self) -> list[Check]:
        readable, error = self.security_readable()
        checks = [Check("security", "Fuentes", "Accesos y RDP (registro Security)", "ok" if readable else "info",
                        "Legible" if readable else "Sin permiso de lectura: se omiten accesos, RDP y fuerza bruta",
                        "" if readable else "Ejecute Configurar permisos (una vez, pide administrador) y cierre sesión")]
        log = self.settings.firewall_log_path
        try:
            exists = log.exists() and os.access(log, os.R_OK)
        except OSError:  # the default System32 folder denies even the existence check without admin
            exists = False
        checks.append(Check("firewall", "Fuentes", "Log del firewall", "ok" if exists else "info",
                            str(log) if exists else "No configurado: se omiten los intentos de conexión bloqueados",
                            "" if exists else "Ejecute Configurar permisos (una vez, pide administrador)"))
        sysmon = self.sysmon_installed()
        checks.append(Check("sysmon", "Fuentes", "Sysmon (opcional)", "ok" if sysmon else "info",
                            "Instalado" if sysmon else "No instalado: sin conexiones por proceso ni borrados de archivos",
                            "" if sysmon else "Opcional, ver README\\README.md (fase 5)"))
        return checks

    def pull_model(self, name: str):
        """Downloads a model through the local Ollama; yields (status, completed, total)."""
        from ollama import Client
        client = Client(host=self.settings.validated_ollama_host())
        for progress in client.pull(name, stream=True):
            yield progress.status or "", progress.completed or 0, progress.total or 0
