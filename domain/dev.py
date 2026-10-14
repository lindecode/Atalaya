"""What a developer's machine is running: languages, servers, how exposed they are, debug ports and tunnels.

Pure functions over process names, paths and addresses, shared by the detection rules, the live network watcher and
the Desarrollo page.
"""
from __future__ import annotations

import ipaddress
import re
from typing import NamedTuple


class Runtime(NamedTuple):
    key: str
    label: str
    color: str  # node colour on the map; one per language family


# Process image name (lower case, without .exe) -> runtime. Order matters only for readability.
_RUNTIMES = {
    "java": ("java", "Java", "#e76f00"), "javaw": ("java", "Java", "#e76f00"),
    "node": ("node", "Node.js", "#3c873a"), "deno": ("node", "Deno", "#3c873a"), "bun": ("node", "Bun", "#3c873a"),
    "python": ("python", "Python", "#3776ab"), "pythonw": ("python", "Python", "#3776ab"),
    "py": ("python", "Python", "#3776ab"), "uvicorn": ("python", "Python", "#3776ab"),
    "gunicorn": ("python", "Python", "#3776ab"), "jupyter": ("python", "Python", "#3776ab"),
    "dotnet": ("dotnet", ".NET", "#7c4dff"), "iisexpress": ("dotnet", ".NET", "#7c4dff"),
    "go": ("go", "Go", "#00add8"), "gopls": ("go", "Go", "#00add8"), "dlv": ("go", "Go", "#00add8"),
    "ruby": ("ruby", "Ruby", "#cc342d"), "rails": ("ruby", "Ruby", "#cc342d"), "puma": ("ruby", "Ruby", "#cc342d"),
    "php": ("php", "PHP", "#777bb4"), "php-cgi": ("php", "PHP", "#777bb4"),
    "dart": ("dart", "Dart", "#0175c2"), "flutter": ("dart", "Dart", "#0175c2"),
    "cargo": ("rust", "Rust", "#ce422b"), "rustc": ("rust", "Rust", "#ce422b"),
    "postgres": ("db", "Base de datos", "#d4a017"), "mysqld": ("db", "Base de datos", "#d4a017"),
    "mariadbd": ("db", "Base de datos", "#d4a017"), "redis-server": ("db", "Base de datos", "#d4a017"),
    "mongod": ("db", "Base de datos", "#d4a017"), "sqlservr": ("db", "Base de datos", "#d4a017"),
    "com.docker.backend": ("container", "Docker/WSL", "#2496ed"), "wslrelay": ("container", "Docker/WSL", "#2496ed"),
    "vpnkit": ("container", "Docker/WSL", "#2496ed"), "dockerd": ("container", "Docker/WSL", "#2496ed"),
    "nginx": ("web", "Servidor web", "#009639"), "httpd": ("web", "Servidor web", "#009639"),
    "caddy": ("web", "Servidor web", "#009639"),
    "code": ("ide", "Editor/IDE", "#8e8e8e"), "idea64": ("ide", "Editor/IDE", "#8e8e8e"),
    "pycharm64": ("ide", "Editor/IDE", "#8e8e8e"), "nbcode64": ("ide", "Editor/IDE", "#8e8e8e"),
    "devenv": ("ide", "Editor/IDE", "#8e8e8e"), "rider64": ("ide", "Editor/IDE", "#8e8e8e"),
    "webstorm64": ("ide", "Editor/IDE", "#8e8e8e"), "studio64": ("ide", "Editor/IDE", "#8e8e8e"),
}
OTHER = Runtime("other", "Otro", "#9aa4b2")
DEV_RUNTIMES = {"java", "node", "python", "dotnet", "go", "ruby", "php", "dart", "rust", "db", "container", "web"}

# Ports that hand out code execution when reachable from the network (debuggers, notebooks, devtools)
DEBUG_PORTS = {5005: "JDWP (depurador de Java)", 9229: "Inspector de Node.js",
               9222: "Chrome DevTools (depuración remota)", 5678: "debugpy (depurador de Python)",
               8888: "Jupyter", 2345: "Delve (depurador de Go)"}
# Programs whose job is to publish a local server on the Internet
TUNNELS = {"ngrok": "ngrok", "cloudflared": "Cloudflare Tunnel", "lt": "localtunnel", "devtunnel": "Dev Tunnels",
           "code-tunnel": "VS Code Tunnels", "frpc": "frp", "bore": "bore", "zrok": "zrok", "pinggy": "Pinggy",
           "tailscale-funnel": "Tailscale Funnel", "localxpose": "LocalXpose", "loclx": "LocalXpose"}

SCOPE_LOCAL, SCOPE_LAN, SCOPE_ALL = "local", "lan", "all"
SCOPE_LABELS = {SCOPE_LOCAL: ("Solo este equipo", "This computer only"), SCOPE_LAN: ("Red local", "Local network"),
                SCOPE_ALL: ("Todas las redes", "Every network")}


def _image(name: str | None) -> str:
    return re.sub(r"\.exe$", "", str(name or "").strip().casefold())


def runtime(name: str | None, path: str | None = None) -> Runtime:
    """Runtime of a process from its image name, falling back to well-known install folders in its path."""
    found = _RUNTIMES.get(_image(name))
    if found:
        return Runtime(*found)
    folder = str(path or "").replace("/", "\\").casefold()
    for marker, key in (("\\java\\", "java"), ("\\jdk", "java"), ("\\nodejs\\", "node"), ("\\python3", "python"),
                        ("\\dotnet\\", "dotnet"), ("\\go\\bin\\", "go")):
        if marker in folder:
            return next(Runtime(*value) for value in _RUNTIMES.values() if value[0] == key)
    return OTHER


def tunnel(name: str | None) -> str | None:
    return TUNNELS.get(_image(name))


def ip(value: str | None):
    try:
        return ipaddress.ip_address(str(value or "").split("%")[0])
    except ValueError:
        return None


def scope(listen_address: str | None) -> str:
    """How far a listening socket reaches: loopback, one private interface, or every interface."""
    address = ip(listen_address)
    if address is None:
        return SCOPE_LOCAL
    if address.is_unspecified:
        return SCOPE_ALL
    if address.is_loopback:
        return SCOPE_LOCAL
    return SCOPE_ALL if address.is_global else SCOPE_LAN


def origin(remote_address: str | None) -> str | None:
    """'local' (this machine), 'lan' (private network) or 'internet' for a peer address; None if unusable."""
    address = ip(remote_address)
    if address is None or address.is_unspecified:
        return None
    if getattr(address, "ipv4_mapped", None):
        address = address.ipv4_mapped
    if address.is_loopback:
        return "local"
    return "internet" if address.is_global else "lan"


def debug_port(port: int | None) -> str | None:
    return DEBUG_PORTS.get(int(port)) if port is not None else None


SECRET = re.compile(r"(?i)((?:pass(?:word|wd)?|pwd|token|secret|api[_-]?key|key|auth|credential)s?[=:\s]+)(\S+)")
URL_CREDENTIALS = re.compile(r"(?i)(\w+://)[^/\s:@]+:[^/\s@]+@")


def redact_command(command: str | None, limit: int = 300) -> str:
    """Command line without passwords, tokens or URL credentials; shown on screen, never sent anywhere."""
    text = URL_CREDENTIALS.sub(r"\1***:***@", str(command or ""))
    text = SECRET.sub(r"\1***", text)
    return text[:limit] + ("…" if len(text) > limit else "")


def java_target(command: str | None) -> str | None:
    """The jar or main class of a Java command line ('-jar app.jar' or the first argument that looks like a class)."""
    parts = str(command or "").split()
    for index, part in enumerate(parts):
        if part == "-jar" and index + 1 < len(parts):
            return parts[index + 1].strip('"').replace("\\", "/").rsplit("/", 1)[-1]
    skip = False
    for part in parts[1:]:
        if skip:
            skip = False
            continue
        if part in {"-cp", "-classpath", "--class-path", "-p", "--module-path"}:
            skip = True
            continue
        if not part.startswith("-") and re.fullmatch(r"[\w$]+(\.[\w$]+)+", part):
            return part
    return None
