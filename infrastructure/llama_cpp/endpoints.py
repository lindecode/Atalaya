from __future__ import annotations

import socket
from urllib.parse import urlparse


_runtime_hosts: dict[str, str] = {}


def configured_host(settings, role: str) -> str:
    if role == "chat":
        return settings.validated_llama_cpp_host()
    if role == "embedding":
        return settings.validated_llama_cpp_embedding_host()
    raise ValueError("Rol de llama.cpp inválido")


def runtime_host(settings, role: str) -> str:
    """Return the endpoint selected for this Atalaya process."""
    return _runtime_hosts.get(role, configured_host(settings, role))


def select_available_host(settings, role: str) -> str:
    """Keep the configured loopback port when free, otherwise select an ephemeral one."""
    preferred = configured_host(settings, role)
    parsed = urlparse(preferred)
    port = parsed.port or (11435 if role == "chat" else 11436)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            probe.bind(("127.0.0.1", port))
            selected = port
        except OSError:
            probe.bind(("127.0.0.1", 0))
            selected = probe.getsockname()[1]
    host = f"http://127.0.0.1:{selected}"
    _runtime_hosts[role] = host
    return host


def remember_host(role: str, host: str) -> None:
    _runtime_hosts[role] = host


def forget_host(role: str) -> None:
    _runtime_hosts.pop(role, None)
