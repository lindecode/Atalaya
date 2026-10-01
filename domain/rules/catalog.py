from __future__ import annotations

import ipaddress
from collections import defaultdict
from pathlib import PureWindowsPath
from typing import Callable

from domain.models import AlertCandidate, EvidenceView
from domain.rules.base import candidate, dt, has_window


Rule = Callable[[EvidenceView, object], list[AlertCandidate]]


def _group(rows, key):
    result = defaultdict(list)
    for row in rows:
        value = row.get(key)
        if value and value not in {"-", "::1", "127.0.0.1"}:
            result[str(value)].append(row)
    return result


def r01(view, cfg):
    alerts = []
    failures = [r for r in view.auth_events if r["event_id"] == 4625]
    seen = set()
    for field in ("source_ip", "target_user"):
        for entity, rows in _group(failures, field).items():
            window = has_window(rows, cfg.brute_force_count, cfg.brute_force_minutes)
            if window and (field, entity) not in seen:
                seen.add((field, entity))
                alerts.append(candidate("R01", "high", "Posible fuerza bruta", f"{field}:{entity}", window, "auth_event", {"count": len(window), field: entity}, window[-1]["ts"], dt(window[0]["ts"]).strftime("%Y%m%d%H%M")))
    return alerts


def r02(view, cfg):
    alerts = []
    for ip, failures in _group([r for r in view.auth_events if r["event_id"] == 4625], "source_ip").items():
        burst = has_window(failures, cfg.brute_force_count, cfg.brute_force_minutes)
        if not burst:
            continue
        end = dt(burst[-1]["ts"])
        successes = [r for r in view.auth_events if r["event_id"] == 4624 and r.get("source_ip") == ip and end <= dt(r["ts"]) <= end + __import__("datetime").timedelta(minutes=30)]
        if successes:
            rows = burst + successes[:1]
            alerts.append(candidate("R02", "critical", "Fuerza bruta seguida de acceso", ip, rows, "auth_event", {"source_ip": ip, "failures": len(burst)}, rows[-1]["ts"]))
    return alerts


def r03(view, cfg):
    alerts = []
    for row in view.auth_events:
        if not (row["event_id"] == 1149 or (row["event_id"] == 4624 and row.get("logon_type") == 10)):
            continue
        ip = row.get("source_ip") or "unknown"
        if ("logon_source", ip) in view.baseline:
            continue
        try:
            severity = "critical" if ipaddress.ip_address(ip).is_global else "high"
        except ValueError:
            severity = "high"
        alerts.append(candidate("R03", severity, "Acceso remoto interactivo nuevo", ip, [row], "auth_event", {"source_ip": ip}, row["ts"]))
    return alerts


def r04(view, cfg):
    return [candidate("R04", "medium", "Inicio de sesión de red inesperado", str(r.get("source_ip")), [r], "auth_event", {"user": r.get("target_user")}, r["ts"])
            for r in view.auth_events if r["event_id"] == 4624 and r.get("logon_type") == 3 and not str(r.get("target_user") or "").endswith("$") and ("logon_source", str(r.get("source_ip"))) not in view.baseline]


def r05(view, cfg):
    alerts = []
    for r in view.connections:
        if r.get("direction") != "listen": continue
        value = f"{r.get('process_name') or '?'}|{r.get('lport')}"
        if ("listen_port", value) not in view.baseline:
            alerts.append(candidate("R05", "medium", "Puerto nuevo en escucha", value, [r], "connection", {"address": r.get("laddr"), "port": r.get("lport")}, r["ts"]))
    return alerts


def r06(view, cfg):
    suspicious = ("\\temp\\", "\\downloads\\", "\\appdata\\local\\temp\\", "\\public\\", "\\$recycle.bin\\")
    return [candidate("R06", "high", "Ejecutable en ruta sospechosa con red", str(r.get("process_path")), [r], "connection", {"remote": r.get("raddr")}, r["ts"])
            for r in view.connections if r.get("raddr") and any(part in (str(r.get("process_path") or "").replace("/", "\\").casefold()) for part in suspicious)]


def r07(view, cfg):
    return [candidate("R07", "medium", "Puerto remoto sospechoso", str(r.get("raddr")), [r], "connection", {"port": r.get("rport")}, r["ts"])
            for r in view.connections if r.get("direction") == "outbound" and r.get("rport") in cfg.suspicious_ports]


def r08(view, cfg):
    rows = [r for r in view.file_events if r.get("action") in {"modified", "deleted", "moved"}]
    window = has_window(rows, cfg.mass_file_count, cfg.mass_file_minutes)
    return [candidate("R08", "critical", "Modificación masiva de archivos", "watch_dirs", window, "file_event", {"count": len(window)}, window[-1]["ts"], dt(window[0]["ts"]).strftime("%Y%m%d%H%M"))] if window else []


def r09(view, cfg):
    alerts = []
    ransom = [r for r in view.file_events if "decrypt" in PureWindowsPath(r["path"]).name.casefold() or "readme" in PureWindowsPath(r["path"]).name.casefold()]
    if ransom:
        alerts.append(candidate("R09", "high", "Posible nota de rescate", "ransom_note", ransom, "file_event", {"count": len(ransom)}, ransom[-1]["ts"]))
    extensions = _group([r for r in view.file_events if r.get("action") == "moved"], "extension")
    for ext, rows in extensions.items():
        if len(rows) >= cfg.anomalous_extension_count:
            alerts.append(candidate("R09", "high", "Extensión anómala masiva", ext, rows, "file_event", {"extension": ext, "count": len(rows)}, rows[-1]["ts"]))
    return alerts


def r10(view, cfg):
    return [candidate("R10", "high", "Nueva persistencia", f"{r['kind']}:{r.get('name')}", [r], "persistence_item", {"command": r.get("command")}, r["first_seen"])
            for r in view.persistence_items if r.get("active") and ("persistence", f"{r['kind']}|{r['location']}|{r.get('name') or ''}") not in view.baseline]


def r11(view, cfg):
    executable = {".exe", ".dll", ".ps1", ".bat", ".cmd", ".vbs", ".js", ".hta", ".scr", ".lnk", ".msi"}
    return [candidate("R11", "medium", "Ejecutable o script nuevo", r["path"], [r], "file_event", {"sha256": r.get("sha256")}, r["ts"])
            for r in view.file_events if r.get("action") in {"created", "observed_new"} and r.get("extension") in executable and "\\program files\\" not in r["path"].replace("/", "\\").casefold()]


def r12(view, cfg):
    alerts = []
    for ip, rows in _group([r for r in view.firewall_events if r.get("action") == "DROP"], "src_ip").items():
        window = has_window(rows, cfg.port_scan_count, 2)
        if window and len({r.get("dst_port") for r in window}) >= cfg.port_scan_count:
            alerts.append(candidate("R12", "high", "Escaneo de puertos", ip, window, "firewall_event", {"ports": len({r.get('dst_port') for r in window})}, window[-1]["ts"]))
    return alerts


def r13(view, cfg):
    return [candidate("R13", "critical", "Registro de auditoría borrado", "security_log", [r], "auth_event", {}, r["ts"]) for r in view.auth_events if r["event_id"] == 1102]


def r14(view, cfg):
    return [candidate("R14", "medium", "Cambio de privilegios o cuenta", str(r.get("target_user")), [r], "auth_event", {"event_id": r["event_id"]}, r["ts"]) for r in view.auth_events if r["event_id"] in {4720, 4732}]


ALL_RULES: tuple[Rule, ...] = (r01, r02, r03, r04, r05, r06, r07, r08, r09, r10, r11, r12, r13, r14)
