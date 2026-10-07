from __future__ import annotations

import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from infrastructure.llama_cpp.client import LlamaCppClient


def configured(settings) -> bool:
    return settings.llama_cpp_executable.is_file() and settings.llama_cpp_model_path.is_file()


def expected_server(settings) -> bool:
    """The listener must be the configured executable with the configured model."""
    import psutil
    parsed = urlparse(settings.validated_llama_cpp_host())
    port = parsed.port or 11435
    executable = str(settings.llama_cpp_executable.resolve()).casefold()
    model = str(settings.llama_cpp_model_path.resolve()).casefold()
    try:
        for connection in psutil.net_connections(kind="tcp"):
            if not connection.laddr or connection.laddr.port != port or connection.status != psutil.CONN_LISTEN:
                continue
            if connection.laddr.ip not in {"127.0.0.1", "::1"} or connection.pid is None:
                continue
            process = psutil.Process(connection.pid)
            command = " ".join(process.cmdline()).casefold()
            if str(Path(process.exe()).resolve()).casefold() == executable and model in command:
                return True
    except (OSError, psutil.Error):
        return False
    return False


def start_if_needed(settings, popen=subprocess.Popen):
    """Start a bundled llama-server only when explicitly selected/configured."""
    client = LlamaCppClient(settings.validated_llama_cpp_host(), 1)
    if client.health() and expected_server(settings):
        return None
    if client.health():
        raise RuntimeError("El puerto de llama.cpp responde, pero no pertenece al runtime configurado de Atalaya")
    if not configured(settings):
        raise RuntimeError("Falta llama-server.exe o el modelo GGUF configurado")
    parsed = urlparse(settings.validated_llama_cpp_host())
    command = [str(settings.llama_cpp_executable), "--model", str(settings.llama_cpp_model_path),
               "--host", "127.0.0.1", "--port", str(parsed.port or 11435),
               "--ctx-size", str(settings.llama_cpp_context_size), "--embedding"]
    logs = settings.database_path.parent.parent / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    output = open(logs / "llama-server.log", "ab")
    try:
        return popen(command, cwd=Path(settings.llama_cpp_executable).parent, stdout=output,
                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        output.close()
        raise


def ensure_running(settings, timeout: float = 45.0) -> None:
    client = LlamaCppClient(settings.validated_llama_cpp_host(), 1)
    if client.health() and expected_server(settings):
        return
    start_if_needed(settings)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.health() and expected_server(settings):
            return
        time.sleep(0.5)
    raise RuntimeError("llama-server no estuvo listo dentro del tiempo esperado")
