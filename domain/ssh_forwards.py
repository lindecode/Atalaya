"""SSH port forwards from an ssh command line and from ~/.ssh/config (pure parsing).

local   (-L, LocalForward):   this computer listens on `listen` and forwards to `target` as seen from the server
remote  (-R, RemoteForward):  the server listens on `listen` and forwards to `target` as seen from this computer
dynamic (-D, DynamicForward): this computer listens on `listen` as a SOCKS proxy through the server
"""
from __future__ import annotations

import fnmatch
import re
import shlex

# ssh options that take a value (OpenSSH manual): the destination is the first argument that is not one of these
VALUE_OPTIONS = set("BbcDEeFIiJLlmOoPpQRSWw")
OPTION_KINDS = {"L": "local", "R": "remote", "D": "dynamic"}
CONFIG_KINDS = {"localforward": "local", "remoteforward": "remote", "dynamicforward": "dynamic"}


def _split_address(text: str) -> list[str]:
    """'[::1]:8090:localhost:80' -> ['::1', '8090', 'localhost', '80'] (brackets protect IPv6 colons)."""
    return [part.strip("[]") for part in re.findall(r"\[[^\]]*\]|[^:]+", text)]


def forward(kind: str, spec: str) -> dict | None:
    """One -L/-R/-D value: [bind:]port[:host:hostport]. Unix sockets and malformed values are skipped."""
    parts = _split_address(spec.strip())
    if kind == "dynamic":
        bind, port = (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0] if parts else "")
        return {"kind": kind, "bind": bind, "listen": int(port), "target": None} if port.isdigit() else None
    if len(parts) == 4:
        bind, port, host, hostport = parts
    elif len(parts) == 3:
        bind, (port, host, hostport) = None, parts
    elif kind == "remote" and len(parts) in (1, 2):  # -R [bind:]port: remote dynamic SOCKS
        bind, port = (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])
        return {"kind": kind, "bind": bind, "listen": int(port), "target": None} if port.isdigit() else None
    else:
        return None
    if not (port.isdigit() and hostport.isdigit()):
        return None
    return {"kind": kind, "bind": bind, "listen": int(port), "target": f"{host}:{hostport}"}


def parse_command(command: list[str] | str) -> dict:
    """{'destination': alias or user@host, 'port': -p, 'forwards': [...]} from an ssh command line."""
    args = shlex.split(command, posix=False) if isinstance(command, str) else list(command)
    args = args[1:]  # the program itself
    destination, port, forwards = None, None, []
    index = 0
    while index < len(args):
        arg = args[index].strip('"')
        if destination is None and arg.startswith("-") and len(arg) > 1:
            letter, rest = arg[1], arg[2:]
            if letter in VALUE_OPTIONS:
                value = rest or (args[index + 1].strip('"') if index + 1 < len(args) else "")
                index += 0 if rest else 1
                if letter in OPTION_KINDS:
                    found = forward(OPTION_KINDS[letter], value)
                    if found:
                        forwards.append(found)
                elif letter == "p" and value.isdigit():
                    port = int(value)
                elif letter == "o":
                    key, _, option = value.replace("=", " ", 1).partition(" ")
                    kind = CONFIG_KINDS.get(key.casefold())
                    if kind:
                        found = _config_forward(kind, option)
                        if found:
                            forwards.append(found)
            # flags without value (-T, -N, -4…) need nothing
        elif destination is None:
            destination = arg
        else:
            break  # the remote command starts here
        index += 1
    host = destination.rsplit("@", 1)[-1] if destination else None
    return {"destination": host, "port": port, "forwards": forwards}


def _config_forward(kind: str, value: str) -> dict | None:
    """Config syntax: 'LocalForward [bind:]port host:hostport' (space between the two halves)."""
    pieces = value.split()
    if kind == "dynamic":
        return forward(kind, pieces[0]) if pieces else None
    if len(pieces) == 2:
        return forward(kind, f"{pieces[0]}:{pieces[1]}")
    return forward(kind, pieces[0]) if len(pieces) == 1 else None


def parse_config(text: str) -> list[dict]:
    """Host blocks of ~/.ssh/config: [{'patterns': [...], 'hostname', 'port', 'forwards': [...]}]."""
    blocks, current = [], {"patterns": ["*"], "hostname": None, "port": None, "forwards": []}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.replace("=", " ", 1).partition(" ")
        key, value = key.casefold(), value.strip()
        if key == "host":
            blocks.append(current)
            current = {"patterns": value.split(), "hostname": None, "port": None, "forwards": []}
        elif key == "match":
            blocks.append(current)
            current = {"patterns": [], "hostname": None, "port": None, "forwards": []}  # not evaluated
        elif key == "hostname" and current["hostname"] is None:
            current["hostname"] = value
        elif key == "port" and current["port"] is None and value.isdigit():
            current["port"] = int(value)
        elif key in CONFIG_KINDS:
            found = _config_forward(CONFIG_KINDS[key], value)
            if found:
                current["forwards"].append(found)
    blocks.append(current)
    return [block for block in blocks if block["patterns"]]


def host_settings(blocks: list[dict], alias: str | None) -> dict:
    """What ssh would apply to `alias`: first HostName/Port found, every matching forward (ssh semantics)."""
    result = {"hostname": None, "port": None, "forwards": []}
    if not alias:
        return result
    for block in blocks:
        positive = [p for p in block["patterns"] if not p.startswith("!")]
        negative = [p[1:] for p in block["patterns"] if p.startswith("!")]
        if any(fnmatch.fnmatch(alias, p) for p in negative) or not any(fnmatch.fnmatch(alias, p) for p in positive):
            continue
        result["hostname"] = result["hostname"] or block["hostname"]
        result["port"] = result["port"] or block["port"]
        result["forwards"] += block["forwards"]
    return result
