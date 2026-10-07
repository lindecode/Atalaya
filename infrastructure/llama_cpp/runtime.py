from __future__ import annotations

import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from infrastructure.llama_cpp.client import LlamaCppClient
from infrastructure.llama_cpp.credentials import key_path, load_or_create_key


def _role_config(settings, role: str):
    if role == "chat":
        return settings.validated_llama_cpp_host(), settings.llama_cpp_model_path
    if role == "embedding":
        return settings.validated_llama_cpp_embedding_host(), settings.llama_cpp_embedding_model_path
    raise ValueError("Rol de llama.cpp inválido")


def configured(settings, role: str = "chat") -> bool:
    _, model = _role_config(settings, role)
    return settings.llama_cpp_executable.is_file() and model.is_file()


def server_command(settings, role: str) -> list[str]:
    host, model = _role_config(settings, role)
    parsed = urlparse(host)
    command = [str(settings.llama_cpp_executable), "--model", str(model),
               "--host", "127.0.0.1", "--port", str(parsed.port or (11435 if role == "chat" else 11436)),
               "--ctx-size", str(settings.llama_cpp_context_size), "--api-key-file", str(key_path(settings, role)),
               "--no-webui"]
    command.append("--jinja" if role == "chat" else "--embedding")
    return command


def expected_server(settings, role: str = "chat") -> bool:
    """The listener must be the configured executable with the configured model."""
    import psutil
    host, model_path = _role_config(settings, role)
    parsed = urlparse(host)
    port = parsed.port or (11435 if role == "chat" else 11436)
    executable = str(settings.llama_cpp_executable.resolve()).casefold()
    model = str(model_path.resolve()).casefold()
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


def start_if_needed(settings, popen=subprocess.Popen, role: str = "chat"):
    """Start a bundled llama-server only when explicitly selected/configured."""
    host, _ = _role_config(settings, role)
    api_key = load_or_create_key(settings, role)
    client = LlamaCppClient(host, 1, api_key)
    if client.health() and expected_server(settings, role):
        return None
    if client.health():
        raise RuntimeError("El puerto de llama.cpp responde, pero no pertenece al runtime configurado de Atalaya")
    if not configured(settings, role):
        raise RuntimeError(f"Falta llama-server.exe o el modelo GGUF de {role}")
    command = server_command(settings, role)
    logs = settings.database_path.parent.parent / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    output = open(logs / f"llama-server-{role}.log", "ab")
    try:
        return popen(command, cwd=Path(settings.llama_cpp_executable).parent, stdout=output,
                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        output.close()
        raise


def ensure_running(settings, timeout: float = 45.0, role: str = "chat") -> None:
    host, _ = _role_config(settings, role)
    client = LlamaCppClient(host, 1, load_or_create_key(settings, role))
    if client.health() and expected_server(settings, role):
        return
    start_if_needed(settings, role=role)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.health() and expected_server(settings, role):
            return
        time.sleep(0.5)
    raise RuntimeError(f"llama-server ({role}) no estuvo listo dentro del tiempo esperado")
