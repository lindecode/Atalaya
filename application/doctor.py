"""`atalaya doctor`: checks what Atalaya needs on this machine and says how to fix what is missing.

Used by the CLI, the GUI "Primeros pasos" page and start\\diagnostico.bat. Every probe is injectable so the
logic is tested without Ollama, the event log or the real disk.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Literal

Status = Literal["ok", "warn", "fail", "info"]

RUNTIME_MODULES = ("psutil", "win32evtlog", "watchdog", "ollama", "streamlit", "pydantic", "pandas", "plotly", "pystray", "webview")
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
                 disk_free_gb: Callable[[Path], float] = lambda path: shutil.disk_usage(path).free / 1024 ** 3,
                 webview2_version: Callable[[], str | None] = lambda: None,
                 model_puller: Callable[[str], Iterator[tuple[str, int, int]]] | None = None):
        self.settings, self.models = settings, model_service
        self.find_ollama, self.security_readable, self.sysmon_installed = find_ollama, security_readable, sysmon_installed
        self.total_ram_gb, self.module_available, self.disk_free_gb = total_ram_gb, module_available, disk_free_gb
        self.webview2_version, self.model_puller = webview2_version, model_puller

    def run(self) -> list[Check]:
        return self._python() + self._data() + self._operation() + self._llm() + self._sources()

    def _llm(self) -> list[Check]:
        from infrastructure.llm_provider import provider_name
        selected = provider_name(self.settings)
        if selected == "none":
            return [Check("llm-none", "LLM local", "Inteligencia artificial", "info",
                          "Sin proveedor: reglas, recolección y alertas continúan disponibles",
                          "Configure Ollama o autorice llama.cpp y un GGUF en IA local")]
        return self._llama_cpp() if selected == "llama_cpp" else self._ollama()

    def _llama_cpp(self) -> list[Check]:
        from infrastructure.llm_provider import effective_settings
        effective = effective_settings(self.settings)
        executable, model = effective.llama_cpp_executable, effective.llama_cpp_model_path
        if not executable.is_file() or not model.is_file():
            missing = executable if not executable.is_file() else model
            return [Check("llama-cpp", "LLM local", "llama.cpp integrado", "warn",
                          f"Falta {missing}: las reglas funcionan, pero no el chat ni las explicaciones",
                          "Configure ATALAYA_LLAMA_CPP_SERVER y ATALAYA_LLAMA_CPP_MODEL")]
        try:
            installed = self.models.available()
        except Exception as exc:
            return [Check("llama-cpp", "LLM local", "llama.cpp integrado", "warn",
                          f"Configurado pero no responde: {exc}", "Reinicie Atalaya y revise logs\\llama-server.log")]
        size = model.stat().st_size / 1e9
        checks = [Check("llama-cpp", "LLM local", "llama.cpp integrado", "ok",
                        f"En marcha · {model.name} · {size:.1f} GB · {len(installed)} modelo(s)")]
        embedding = effective.llama_cpp_embedding_model_path
        if not embedding.is_file():
            checks.append(Check("llama-cpp-embedding", "LLM local", "Embeddings llama.cpp", "info",
                                "Sin modelo dedicado: RAG usa búsqueda léxica",
                                "Configure ATALAYA_LLAMA_CPP_EMBEDDING_MODEL para búsqueda semántica"))
        else:
            from infrastructure.llama_cpp.client import LlamaCppClient
            from infrastructure.llama_cpp.credentials import load_or_create_key
            from infrastructure.llama_cpp.endpoints import runtime_host
            ready = LlamaCppClient(runtime_host(self.settings, "embedding"), 2,
                                   load_or_create_key(self.settings, "embedding")).health()
            checks.append(Check("llama-cpp-embedding", "LLM local", "Embeddings llama.cpp",
                                "ok" if ready else "warn", f"{embedding.name} · {'en marcha' if ready else 'detenido'}",
                                "Reinicie Atalaya" if not ready else ""))
        return checks

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
        webview2 = self.webview2_version()
        checks.append(Check("window", "Programa", "Ventana de la aplicación (WebView2)", "ok" if webview2 else "info",
                            f"WebView2 {webview2}" if webview2 else "No disponible: el panel se abre en el navegador",
                            "" if webview2 else "Instale «winget install Microsoft.EdgeWebView2Runtime» para usar la ventana propia"))
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

    def _operation(self) -> list[Check]:
        checks: list[Check] = []
        database = self.settings.database_path
        if not database.exists():
            return [Check("database", "Operación", "Base de datos", "info", "Todavía no inicializada",
                          "Abra Atalaya o ejecute «python main.py status»")]
        try:
            with sqlite3.connect(database) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                chunks = (connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
                          if "knowledge_chunks" in tables else 0)
                last_run = (connection.execute(
                    "SELECT finished_at,status FROM runs ORDER BY id DESC LIMIT 1").fetchone()
                            if "runs" in tables else None)
            checks.append(Check("database", "Operación", "Base de datos", "ok" if integrity == "ok" else "fail",
                                f"Integridad: {integrity} · {database.stat().st_size / 1024 ** 2:.1f} MB",
                                "Restaure un backup verificado" if integrity != "ok" else ""))
            checks.append(Check("rag", "Operación", "Índice RAG", "ok" if chunks else "info",
                                f"{chunks} fragmento(s)" if chunks else "Sin documentación indexada",
                                "Ejecute «python main.py rag index»" if not chunks else ""))
            checks.append(Check("last-run", "Operación", "Última recolección", "ok" if last_run else "info",
                                f"{last_run[0] or 'en curso'} · {last_run[1]}" if last_run else "Todavía no hay ejecuciones"))
        except (OSError, sqlite3.Error) as exc:
            checks.append(Check("database", "Operación", "Base de datos", "fail", str(exc),
                                "Ejecute el diagnóstico con Atalaya detenida o restaure un backup"))
        lock = database.with_suffix(".cycle.lock")
        checks.append(Check("cycle-lock", "Operación", "Bloqueo del ciclo", "warn" if lock.exists() else "ok",
                            str(lock) if lock.exists() else "Sin bloqueo abandonado",
                            "Detenga Atalaya y elimine el archivo solo si no hay ningún ciclo activo" if lock.exists() else ""))
        backups = (sorted(self.settings.backup_dir.glob("*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
                   if self.settings.backup_dir.exists() else [])
        checks.append(Check("backup", "Operación", "Backup local", "ok" if backups else "info",
                            f"Último: {backups[0].name}" if backups else "No hay backups",
                            "Cree uno desde Herramientas o con «python main.py backup»" if not backups else ""))
        return checks

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
        for role, label in (("analysis", "análisis"), ("chat", "chat"), ("summary", "resumen")):
            name = self.models.current(role)
            model = installed.get(name) or installed.get(f"{name}:latest")
            if not model:
                checks.append(Check(f"model-{role}", "LLM local", f"Modelo de {label}", "warn",
                                    f"{name} no está descargado", f"Descárguelo con «ollama pull {name}»"))
            elif role == "chat" and not model["tools"]:
                checks.append(Check("model-chat", "LLM local", "Modelo de chat", "warn",
                                    f"{name} no admite herramientas: el chat no funcionará",
                                    "Elija un modelo con tools (p. ej. qwen3.5:4b)"))
            else:
                checks.append(Check(f"model-{role}", "LLM local", f"Modelo de {label}", "ok",
                                    f"{name} · {model.get('parameters') or '?'} · {model.get('size_gb', '?')} GB"))
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
        if self.model_puller is None:
            raise RuntimeError("Descarga de modelos no disponible en este contexto")
        yield from self.model_puller(name)
