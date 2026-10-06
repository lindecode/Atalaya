from __future__ import annotations

import ipaddress
from collections import defaultdict
from pathlib import PureWindowsPath
from typing import Callable

from domain.models import AlertCandidate, EvidenceView
from domain.rules.base import INVALID_IPS, baseline_key, candidate, dt, has_distinct_window, has_window


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
        if baseline_key("R03", row) in view.baseline:
            continue
        try:
            severity = "critical" if ipaddress.ip_address(ip).is_global else "high"
        except ValueError:
            severity = "high"
        alerts.append(candidate("R03", severity, "Acceso remoto interactivo nuevo", ip, [row], "auth_event", {"source_ip": ip}, row["ts"]))
    return alerts


def r04(view, cfg):
    return [candidate("R04", "medium", "Inicio de sesión de red inesperado", str(r.get("source_ip")), [r], "auth_event", {"user": r.get("target_user")}, r["ts"])
            for r in view.auth_events if r["event_id"] == 4624 and r.get("logon_type") == 3 and str(r.get("source_ip") or "") not in INVALID_IPS
            and not str(r.get("target_user") or "").endswith("$") and baseline_key("R04", r) not in view.baseline]


def r05(view, cfg):
    alerts = []
    seen = set()
    for r in view.connections:
        if r.get("direction") != "listen": continue
        key = baseline_key("R05", r)
        if key not in view.baseline and key not in seen:
            seen.add(key)
            alerts.append(candidate("R05", "medium", "Puerto nuevo en escucha", key[1], [r], "connection", {"address": r.get("laddr"), "port": r.get("lport")}, r["ts"], "first"))
    return alerts


def r06(view, cfg):
    suspicious = ("\\temp\\", "\\downloads\\", "\\appdata\\local\\temp\\", "\\public\\", "\\$recycle.bin\\")
    return [candidate("R06", "high", "Ejecutable en ruta sospechosa con red", str(r.get("process_path")), [r], "connection", {"remote": r.get("raddr")}, r["ts"])
            for r in view.connections if r.get("raddr") and any(part in (str(r.get("process_path") or "").replace("/", "\\").casefold()) for part in suspicious)]


def r07(view, cfg):
    return [candidate("R07", "medium", "Puerto remoto sospechoso", str(r.get("raddr")), [r], "connection", {"port": r.get("rport")}, r["ts"])
            for r in view.connections if r.get("direction") == "outbound" and r.get("rport") in cfg.suspicious_ports]


def _windows_prefix(path) -> str:
    return str(path).replace("/", "\\").rstrip("\\").casefold() + "\\"


def r08(view, cfg):
    # %TEMP% churns constantly (browsers, installers): counting it would make R08 cry wolf
    excluded = tuple(_windows_prefix(p) for p in getattr(cfg, "mass_file_exclude_dirs", ()))
    rows = [r for r in view.file_events if r.get("action") in {"modified", "deleted", "moved"}
            and not _windows_prefix(r["path"]).startswith(excluded)]
    window = has_window(rows, cfg.mass_file_count, cfg.mass_file_minutes)
    return [candidate("R08", "critical", "Modificación masiva de archivos", "watch_dirs", window, "file_event", {"count": len(window)}, window[-1]["ts"], dt(window[0]["ts"]).strftime("%Y%m%d%H%M"))] if window else []


RANSOM_KEYWORDS = ("decrypt", "ransom", "restore_files", "recover_files", "how_to_back", "your_files", "files_encrypted")
NOTE_EXTENSIONS = {".txt", ".html", ".htm", ".hta", ".rtf", ".url"}
# Downloads and editors rename these on completion; that is not an extension change by malware
TRANSIENT_EXTENSIONS = {".tmp", ".crdownload", ".part", ".partial", ".download", ".swp", ".~tmp"}
NOTE_SPREAD_FOLDERS = 3


def r09(view, cfg):
    alerts = []
    notes = [r for r in view.file_events if r.get("action") in {"created", "observed_new"}
             and PureWindowsPath(r["path"]).suffix.casefold() in NOTE_EXTENSIONS]
    keyword = [r for r in notes if any(word in PureWindowsPath(r["path"]).stem.casefold() for word in RANSOM_KEYWORDS)]
    if keyword:
        alerts.append(candidate("R09", "high", "Posible nota de rescate", "ransom_note", keyword, "file_event", {"count": len(keyword)}, keyword[-1]["ts"]))
    # Ransomware drops the same note (often a plain README.txt) in every folder it encrypts
    by_name = defaultdict(list)
    for r in notes:
        by_name[PureWindowsPath(r["path"]).name.casefold()].append(r)
    for name, rows in by_name.items():
        if len({str(PureWindowsPath(r["path"]).parent).casefold() for r in rows}) >= NOTE_SPREAD_FOLDERS:
            alerts.append(candidate("R09", "high", "Misma nota en varias carpetas", f"spread:{name}", rows, "file_event", {"name": name, "folders": len(rows)}, rows[-1]["ts"]))
    renames = defaultdict(list)
    for r in view.file_events:
        if r.get("action") != "moved" or not r.get("dest_path"):
            continue
        source, target = PureWindowsPath(r["path"]).suffix.casefold(), PureWindowsPath(r["dest_path"]).suffix.casefold()
        if target and target != source and source not in TRANSIENT_EXTENSIONS:
            renames[target].append(r)
    for ext, rows in renames.items():
        window = has_window(rows, cfg.anomalous_extension_count, 5)
        if window:
            alerts.append(candidate("R09", "high", "Extensión anómala masiva", ext, window, "file_event", {"extension": ext, "count": len(window)}, window[-1]["ts"], dt(window[0]["ts"]).strftime("%Y%m%d%H%M")))
    return alerts


def r10(view, cfg):
    return [candidate("R10", "high", "Nueva persistencia", f"{r['kind']}:{r.get('name')}", [r], "persistence_item", {"command": r.get("command")}, r["first_seen"])
            for r in view.persistence_items if r.get("active") and baseline_key("R10", r) not in view.baseline]


def r11(view, cfg):
    executable = {".exe", ".dll", ".ps1", ".bat", ".cmd", ".vbs", ".js", ".hta", ".scr", ".lnk", ".msi"}
    return [candidate("R11", "medium", "Ejecutable o script nuevo", r["path"], [r], "file_event", {"sha256": r.get("sha256")}, r["ts"])
            for r in view.file_events if r.get("action") in {"created", "observed_new"} and r.get("extension") in executable and "\\program files\\" not in r["path"].replace("/", "\\").casefold()]


def r12(view, cfg):
    alerts = []
    for ip, rows in _group([r for r in view.firewall_events if r.get("action") == "DROP"], "src_ip").items():
        window = has_distinct_window(rows, "dst_port", cfg.port_scan_count, 2)
        if window:
            alerts.append(candidate("R12", "high", "Escaneo de puertos", ip, window, "firewall_event", {"ports": len({r.get('dst_port') for r in window})}, window[-1]["ts"]))
    return alerts


def r13(view, cfg):
    return [candidate("R13", "critical", "Registro de auditoría borrado", "security_log", [r], "auth_event", {}, r["ts"]) for r in view.auth_events if r["event_id"] == 1102]


def r14(view, cfg):
    return [candidate("R14", "medium", "Cambio de privilegios o cuenta", str(r.get("target_user")), [r], "auth_event", {"event_id": r["event_id"]}, r["ts"]) for r in view.auth_events if r["event_id"] in {4720, 4732}]


def r15(view, cfg):
    alerts = []
    by_process = defaultdict(list)
    for row in view.process_snapshots: by_process[row["process_key"]].append(row)
    threshold = int(cfg.process_growth_mb) * 1024 * 1024
    for key, rows in by_process.items():
        ordered = sorted(rows, key=lambda row: row["ts"])
        if len(ordered) < 2: continue
        first, last = ordered[0], ordered[-1]
        before = first.get("private_bytes") or first.get("rss_bytes") or 0
        after = last.get("private_bytes") or last.get("rss_bytes") or 0
        if after - before >= threshold:
            alerts.append(candidate("R15", "medium", "Crecimiento anómalo de memoria", last.get("name") or key,
                                    [first, last], "process_snapshot",
                                    {"growth_mb": round((after-before)/1024**2), "current_mb": round(after/1024**2)},
                                    last["ts"], dt(last["ts"]).strftime("%Y%m%d")))
    return alerts


def r16(view, cfg):
    suspicious = ("\\temp\\", "\\downloads\\", "\\users\\public\\", "\\$recycle.bin\\")
    interpreters = {"powershell.exe", "pwsh.exe", "cmd.exe", "wscript.exe", "cscript.exe", "mshta.exe"}
    latest = {}
    for row in view.process_snapshots: latest[row["process_key"]] = row
    return [candidate("R16", "high", "Proceso activo desde ruta sospechosa", row.get("path") or row.get("name") or key,
                      [row], "process_snapshot", {"parent": row.get("parent_name"), "memory_mb": round((row.get("private_bytes") or row.get("rss_bytes") or 0)/1024**2)},
                      row["ts"], "first")
            for key, row in latest.items()
            if any(part in str(row.get("path") or "").replace("/", "\\").casefold() for part in suspicious)
            and (str(row.get("parent_name") or "").casefold() in interpreters
                 or float(row.get("memory_percent") or 0) >= cfg.process_high_memory_percent)]


ALL_RULES: tuple[Rule, ...] = (r01, r02, r03, r04, r05, r06, r07, r08, r09, r10, r11, r12, r13, r14, r15, r16)
