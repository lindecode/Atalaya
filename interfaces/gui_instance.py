from __future__ import annotations

import json
import os
import secrets
import socket
from dataclasses import asdict, dataclass
from pathlib import Path


LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 8501


@dataclass(frozen=True, slots=True)
class GuiInstance:
    port: int
    token: str
    pid: int
    create_time: float

    @property
    def url(self) -> str:
        return f"http://{LOOPBACK}:{self.port}"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def available_port(preferred: int = DEFAULT_PORT, attempts: int = 50) -> int:
    for port in range(preferred, min(preferred + attempts, 65536)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((LOOPBACK, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No hay un puerto local libre entre {preferred} y {preferred + attempts - 1}")


def write_instance(path: Path, port: int, token: str) -> GuiInstance:
    import psutil
    process = psutil.Process(os.getpid())
    instance = GuiInstance(port, token, process.pid, process.create_time())
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"app": "Atalaya", "version": 1, **asdict(instance)}), encoding="utf-8")
    temporary.replace(path)
    return instance


def read_valid_instance(path: Path, expected_token: str | None = None) -> GuiInstance | None:
    import psutil
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        instance = GuiInstance(int(raw["port"]), str(raw["token"]), int(raw["pid"]), float(raw["create_time"]))
        if raw.get("app") != "Atalaya" or raw.get("version") != 1:
            return None
        if expected_token is not None and not secrets.compare_digest(instance.token, expected_token):
            return None
        process = psutil.Process(instance.pid)
        if abs(process.create_time() - instance.create_time) > 0.01:
            return None
        command = " ".join(process.cmdline()).replace("\\", "/").casefold()
        if "main.py gui" not in command:
            return None
        family = {process.pid, *(child.pid for child in process.children(recursive=True))}
        listeners = [item for item in psutil.net_connections(kind="tcp")
                     if item.pid in family and item.status == psutil.CONN_LISTEN and item.laddr
                     and item.laddr.port == instance.port and item.laddr.ip in {LOOPBACK, "::1"}]
        if not listeners:
            return None
        with socket.create_connection((LOOPBACK, instance.port), timeout=0.4):
            return instance
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, psutil.Error):
        return None


def remove_instance(path: Path, token: str) -> None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if secrets.compare_digest(str(raw.get("token", "")), token):
            path.unlink()
    except (OSError, json.JSONDecodeError):
        pass
