"""Per-section LLM summaries: the aggregated digests they are built from, and where they are kept."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from infrastructure.sqlite.connection import connect

TEXT_LIMIT = 120  # collected strings (names, paths, commands) are cut before reaching the LLM
EXECUTABLE_EXTENSIONS = (".exe", ".dll", ".ps1", ".bat", ".cmd", ".vbs", ".js", ".hta", ".scr", ".lnk", ".msi")
SUSPICIOUS_DIRS = ("%\\temp\\%", "%\\downloads\\%", "%\\users\\public\\%", "%\\$recycle.bin\\%")


def _text(value: Any) -> Any:
    return value[:TEXT_LIMIT] if isinstance(value, str) else value


def _rows(db, sql: str, params=()) -> list[dict]:
    return [{key: _text(value) for key, value in dict(row).items()} for row in db.execute(sql, params)]


def _scalar(db, sql: str, params=()) -> int:
    return int(db.execute(sql, params).fetchone()[0] or 0)


class SQLiteSectionDigests:
    """Aggregated, size-bounded facts per GUI section. Every query is fixed; only times and ports are bound."""

    def __init__(self, settings):
        self.settings = settings

    def digest(self, section: str, window_hours: int, now: str) -> dict[str, Any]:
        end = datetime.fromisoformat(now)
        since = (end - timedelta(hours=window_hours)).isoformat()
        previous = (end - timedelta(hours=2 * window_hours)).isoformat()
        builder = getattr(self, f"_{section}", None)
        if builder is None:
            raise ValueError(f"Sección desconocida: {section}")
        with connect(self.settings.database_path, self.settings.sqlite_busy_timeout_ms, readonly=True) as db:
            current = builder(db, since, now)
            totals_before = self._totals(db, section, previous, since)
        return {"seccion": section, "ventana_horas": window_hours, "datos": current, "ventana_anterior": totals_before}

    # Totals for the previous window of the same length, so the summary can speak of changes
    def _totals(self, db, section: str, start: str, end: str) -> dict[str, int]:
        between = (start, end)
        queries = {
            "panel": {"alertas": "SELECT COUNT(*) FROM alerts WHERE ts>=? AND ts<?"},
            "conexiones": {"ips_remotas": "SELECT COUNT(DISTINCT raddr) FROM connections WHERE ts>=? AND ts<? AND raddr IS NOT NULL"},
            "accesos": {"eventos": "SELECT COUNT(*) FROM auth_events WHERE ts>=? AND ts<?",
                        "fallidos": "SELECT COUNT(*) FROM auth_events WHERE ts>=? AND ts<? AND event_id=4625"},
            "archivos": {"eventos": "SELECT COUNT(*) FROM file_events WHERE ts>=? AND ts<?"},
            "persistencia": {"nuevos": "SELECT COUNT(*) FROM persistence_items WHERE first_seen>=? AND first_seen<?"},
            "firewall": {"bloqueos": "SELECT COUNT(*) FROM firewall_events WHERE ts>=? AND ts<?"},
            "procesos": {"finalizados": "SELECT COUNT(*) FROM process_lifecycle WHERE ended_at>=? AND ended_at<?"},
            "desarrollo": {"clientes_entrantes": """SELECT COUNT(DISTINCT raddr) FROM connections WHERE ts>=? AND ts<?
                                                  AND direction='inbound' AND raddr NOT IN ('127.0.0.1','::1')"""},
        }
        return {name: _scalar(db, sql, between) for name, sql in queries.get(section, {}).items()}

    def _panel(self, db, since, now):
        return {
            "alertas_abiertas_por_severidad": {row["severity"]: row["n"] for row in _rows(db, """
                SELECT severity, COUNT(*) n FROM alerts WHERE status IN ('new','analyzed') GROUP BY severity""")},
            "alertas_abiertas_principales": _rows(db, """
                SELECT rule_id, severity, title FROM alerts WHERE status IN ('new','analyzed')
                ORDER BY CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC,
                         ts DESC LIMIT 8"""),
            "eventos_en_ventana": {
                "alertas": _scalar(db, "SELECT COUNT(*) FROM alerts WHERE ts>=?", (since,)),
                "accesos": _scalar(db, "SELECT COUNT(*) FROM auth_events WHERE ts>=?", (since,)),
                "archivos": _scalar(db, "SELECT COUNT(*) FROM file_events WHERE ts>=?", (since,)),
                "bloqueos_firewall": _scalar(db, "SELECT COUNT(*) FROM firewall_events WHERE ts>=?", (since,)),
                "persistencia_nueva": _scalar(db, "SELECT COUNT(*) FROM persistence_items WHERE first_seen>=?", (since,)),
            },
        }

    def _conexiones(self, db, since, now):
        ports = tuple(int(port) for port in self.settings.suspicious_ports) or (0,)
        marks = ",".join("?" * len(ports))
        return {
            "ips_remotas_distintas": _scalar(db, """SELECT COUNT(DISTINCT raddr) FROM connections
                WHERE ts>=? AND raddr IS NOT NULL AND raddr NOT IN ('127.0.0.1','::1')""", (since,)),
            "procesos_con_red": _scalar(db, "SELECT COUNT(DISTINCT process_name) FROM connections WHERE ts>=? AND raddr IS NOT NULL", (since,)),
            "destinos_principales": _rows(db, """
                SELECT raddr ip, rport puerto, process_name proceso, COUNT(*) observaciones FROM connections
                WHERE ts>=? AND direction='outbound' AND raddr NOT IN ('127.0.0.1','::1')
                GROUP BY raddr, rport, process_name ORDER BY observaciones DESC LIMIT 8""", (since,)),
            "entrantes_principales": _rows(db, """
                SELECT raddr ip, lport puerto_local, process_name proceso, COUNT(*) observaciones FROM connections
                WHERE ts>=? AND direction='inbound' AND raddr NOT IN ('127.0.0.1','::1')
                GROUP BY raddr, lport, process_name ORDER BY observaciones DESC LIMIT 5""", (since,)),
            "puertos_abiertos_a_toda_la_red": _rows(db, """
                SELECT DISTINCT lport puerto, process_name proceso FROM connections
                WHERE ts>=? AND direction='listen' AND laddr IN ('0.0.0.0','::') ORDER BY lport LIMIT 15""", (since,)),
            "salientes_a_puertos_sospechosos": _rows(db, f"""
                SELECT raddr ip, rport puerto, process_name proceso, COUNT(*) observaciones FROM connections
                WHERE ts>=? AND direction='outbound' AND rport IN ({marks})
                GROUP BY raddr, rport, process_name ORDER BY observaciones DESC LIMIT 5""", (since, *ports)),
        }

    def _accesos(self, db, since, now):
        return {
            "eventos_por_id": {str(row["event_id"]): row["n"] for row in _rows(db, """
                SELECT event_id, COUNT(*) n FROM auth_events WHERE ts>=? GROUP BY event_id""", (since,))},
            "origenes_con_fallos": _rows(db, """
                SELECT source_ip ip, COUNT(*) fallos FROM auth_events WHERE ts>=? AND event_id=4625
                GROUP BY source_ip ORDER BY fallos DESC LIMIT 8""", (since,)),
            "cuentas_con_fallos": _rows(db, """
                SELECT target_user cuenta, COUNT(*) fallos FROM auth_events WHERE ts>=? AND event_id=4625
                GROUP BY target_user ORDER BY fallos DESC LIMIT 5""", (since,)),
            "accesos_correctos_por_tipo": {str(row["logon_type"]): row["n"] for row in _rows(db, """
                SELECT logon_type, COUNT(*) n FROM auth_events WHERE ts>=? AND event_id=4624 GROUP BY logon_type""", (since,))},
            "origenes_remotos_correctos": _rows(db, """
                SELECT source_ip ip, target_user cuenta, COUNT(*) n FROM auth_events
                WHERE ts>=? AND (event_id=1149 OR (event_id=4624 AND logon_type IN (3, 10)))
                  AND source_ip NOT IN ('-', '127.0.0.1', '::1')
                GROUP BY source_ip, target_user ORDER BY n DESC LIMIT 8""", (since,)),
        }

    def _archivos(self, db, since, now):
        marks = ",".join("?" * len(EXECUTABLE_EXTENSIONS))
        return {
            "por_accion": {row["action"]: row["n"] for row in _rows(db, """
                SELECT action, COUNT(*) n FROM file_events WHERE ts>=? GROUP BY action""", (since,))},
            "extensiones_principales": _rows(db, """
                SELECT extension, COUNT(*) n FROM file_events WHERE ts>=? AND extension IS NOT NULL
                GROUP BY extension ORDER BY n DESC LIMIT 8""", (since,)),
            "ejecutables_o_scripts_nuevos": _scalar(db, f"""SELECT COUNT(*) FROM file_events WHERE ts>=?
                AND action IN ('created','observed_new') AND extension IN ({marks})""", (since, *EXECUTABLE_EXTENSIONS)),
            "ejecutables_recientes": _rows(db, f"""
                SELECT path ruta, sha256 FROM file_events WHERE ts>=? AND action IN ('created','observed_new')
                AND extension IN ({marks}) ORDER BY ts DESC LIMIT 6""", (since, *EXECUTABLE_EXTENSIONS)),
        }

    def _persistencia(self, db, since, now):
        return {
            "nuevos_por_tipo": {row["kind"]: row["n"] for row in _rows(db, """
                SELECT kind, COUNT(*) n FROM persistence_items WHERE first_seen>=? GROUP BY kind""", (since,))},
            "nuevos_recientes": _rows(db, """
                SELECT kind tipo, name nombre, location ubicacion, command comando FROM persistence_items
                WHERE first_seen>=? ORDER BY first_seen DESC LIMIT 10""", (since,)),
            "desaparecidos": _scalar(db, "SELECT COUNT(*) FROM persistence_items WHERE last_missing_at>=?", (since,)),
            "activos_total": _scalar(db, "SELECT COUNT(*) FROM persistence_items WHERE active=1"),
        }

    def _firewall(self, db, since, now):
        return {
            "por_accion": {row["action"]: row["n"] for row in _rows(db, """
                SELECT action, COUNT(*) n FROM firewall_events WHERE ts>=? GROUP BY action""", (since,))},
            "origenes_principales": _rows(db, """
                SELECT src_ip ip, COUNT(*) bloqueos, COUNT(DISTINCT dst_port) puertos FROM firewall_events
                WHERE ts>=? AND action='DROP' GROUP BY src_ip ORDER BY bloqueos DESC LIMIT 8""", (since,)),
            "puertos_mas_buscados": _rows(db, """
                SELECT dst_port puerto, COUNT(*) bloqueos FROM firewall_events WHERE ts>=? AND action='DROP'
                GROUP BY dst_port ORDER BY bloqueos DESC LIMIT 8""", (since,)),
        }

    def _procesos(self, db, since, now):
        latest = "(SELECT MAX(run_id) FROM process_snapshots)"
        suspicious = " OR ".join("lower(path) LIKE ?" for _ in SUSPICIOUS_DIRS)
        return {
            "activos": _scalar(db, "SELECT COUNT(*) FROM process_lifecycle WHERE active=1"),
            "mayor_memoria_mb": _rows(db, f"""
                SELECT name proceso, ROUND(COALESCE(private_bytes, rss_bytes) / 1048576.0) mb, parent_name padre
                FROM process_snapshots WHERE run_id={latest}
                ORDER BY COALESCE(private_bytes, rss_bytes) DESC LIMIT 8"""),
            "en_rutas_a_revisar": _rows(db, f"""
                SELECT name proceso, path ruta, parent_name padre FROM process_snapshots
                WHERE run_id={latest} AND ({suspicious}) LIMIT 8""", SUSPICIOUS_DIRS),
            "finalizados_en_ventana": _scalar(db, "SELECT COUNT(*) FROM process_lifecycle WHERE ended_at>=?", (since,)),
            "nuevos_en_ventana": _scalar(db, "SELECT COUNT(*) FROM process_lifecycle WHERE first_seen>=?", (since,)),
        }

    def _desarrollo(self, db, since, now):
        """Servers and their reach, who reached them, Docker containers and SSH sessions (no command lines)."""
        from domain import dev
        servers = {}
        for row in _rows(db, """SELECT DISTINCT lport, process_name, laddr FROM connections
                                WHERE ts>=? AND direction='listen'""", (since,)):
            runtime = dev.runtime(row["process_name"])
            reach = dev.scope(row["laddr"])
            if runtime.key not in dev.DEV_RUNTIMES and (reach == dev.SCOPE_LOCAL or dev.windows_service(row["process_name"])):
                continue
            entry = servers.setdefault((row["lport"], row["process_name"]), {
                "puerto": row["lport"], "proceso": row["process_name"], "lenguaje": runtime.label, "alcance": reach,
                "depuracion": dev.debug_port(row["lport"])})
            if reach == dev.SCOPE_ALL or (reach == dev.SCOPE_LAN and entry["alcance"] == dev.SCOPE_LOCAL):
                entry["alcance"] = reach
        listed = sorted(servers.values(), key=lambda s: (s["alcance"] == dev.SCOPE_LOCAL, s["puerto"] or 0))
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        containers = []
        if "docker_observations" in tables:
            # Read raw, not through _rows: its 120-character cut would break the JSON; the fields taken are short
            for (data_json,) in db.execute("""SELECT data_json FROM docker_observations WHERE id IN (
                                      SELECT MAX(id) FROM docker_observations WHERE ts>=? GROUP BY container_id)""", (since,)):
                try:
                    data = json.loads(data_json or "{}")
                except ValueError:
                    continue
                containers.append({key: _text(value) for key, value in {
                    "nombre": data.get("name"), "imagen": data.get("image"), "estado": data.get("state"),
                    "salud": data.get("health"), "reinicios": data.get("restart_count"),
                    "riesgos": ", ".join(sorted({str(r.get("kind")) for r in data.get("risks", [])}))}.items()})
        # Facts already phrased: a small model summarises sentences reliably, it misreads loose field names
        reach_words = {dev.SCOPE_ALL: "todas las redes (0.0.0.0/::)", dev.SCOPE_LAN: "la red local"}
        exposed = [f"{s['proceso']} ({s['lenguaje']}) en el puerto {s['puerto']} acepta conexiones de {reach_words[s['alcance']]}"
                   + (f"; es un puerto de depuración: {s['depuracion']}" if s["depuracion"] else "")
                   for s in listed if s["alcance"] != dev.SCOPE_LOCAL]
        local = [f"{s['proceso']} :{s['puerto']}" for s in listed if s["alcance"] == dev.SCOPE_LOCAL]
        clients = [f"{r['ip']} se conectó al puerto {r['puerto_local']} ({r['proceso']}), {r['n']} observaciones"
                   for r in _rows(db, """
                SELECT raddr ip, lport puerto_local, process_name proceso, COUNT(*) n FROM connections
                WHERE ts>=? AND direction='inbound' AND raddr NOT IN ('127.0.0.1','::1') AND raddr NOT LIKE '127.%'
                GROUP BY raddr, lport, process_name ORDER BY n DESC LIMIT 8""", (since,))]
        tunnel_words = {"socks": "proxy SOCKS (-D)", "local": "túnel local (-L)", "reverse": "túnel inverso (-R)"}
        ssh = []
        for row in _rows(db, """
                SELECT remote_address servidor, remote_port puerto, GROUP_CONCAT(DISTINCT tunnel_types) tuneles,
                       MAX(COALESCE(agent_forwarding, 0)) reenvio FROM ssh_observations
                WHERE ts>=? AND kind='session' AND direction='outbound' AND remote_address IS NOT NULL
                  AND remote_address NOT IN ('127.0.0.1','::1')
                GROUP BY remote_address, remote_port ORDER BY MAX(ts) DESC LIMIT 8""", (since,)):
            kinds = sorted({t for value in str(row["tuneles"] or "").split(",") for t in [value.strip()] if t})
            ssh.append(f"Este equipo abrió una sesión SSH hacia {row['servidor']}:{row['puerto']}"
                       + (" con " + ", ".join(tunnel_words.get(k, k) for k in kinds) if kinds else "")
                       + ("; reenvía el agente SSH (-A)" if row["reenvio"] else ""))
        docker_lines = [f"Contenedor {c['nombre']} ({c['imagen']}) {c['estado']}"
                        # Docker keeps the last health status after a stop: it only means something while running
                        + (f", salud {c['salud']}" if c["salud"] and c["estado"] == "running" else "")
                        + (f", {c['reinicios']} reinicios" if c["reinicios"] else "")
                        + (f"; riesgos: {c['riesgos']}" if c["riesgos"] else "") for c in containers[:12]]
        review = ([f"Puerto de depuración abierto a la red: {s['proceso']} :{s['puerto']} ({s['depuracion']})"
                   for s in listed if s["depuracion"] and s["alcance"] != dev.SCOPE_LOCAL]
                  + [f"{s['proceso']} :{s['puerto']} escucha en {reach_words[s['alcance']]}; si solo lo usa este equipo, "
                     "debería escuchar en 127.0.0.1" for s in listed if s["alcance"] != dev.SCOPE_LOCAL and not s["depuracion"]
                     and dev.runtime(s["proceso"]).key in dev.DEV_RUNTIMES]
                  + [f"Contenedor {c['nombre']}: {c['riesgos']}" for c in containers if c["riesgos"]]
                  + [line for line in ssh if "inverso" in line or "-A" in line])
        return {
            "puntos_a_revisar": review or ["Nada destacable"],
            "servidores_expuestos_a_la_red": exposed or ["Ningún servidor acepta conexiones de fuera de este equipo"],
            "servidores_solo_de_este_equipo": {"cantidad": len(local), "ejemplos": local[:8]},
            "clientes_externos_de_mis_servidores": clients or ["Ningún equipo externo se conectó a estos servidores"],
            "avisos_de_red_por_tipo": {row["kind"]: row["n"] for row in _rows(db, """
                SELECT kind, COUNT(*) n FROM network_notices WHERE ts>=? GROUP BY kind""", (since,))}
            if "network_notices" in tables else {},
            "contenedores_docker": docker_lines or ["Sin contenedores observados"],
            "sesiones_ssh_salientes": ssh or ["Sin sesiones SSH hacia otros equipos"],
        }


class SQLiteSectionSummaryStore:
    def __init__(self, settings):
        self.settings = settings

    def save(self, section: str, created_at: str, trigger: str, window_hours: int, model: str | None,
             digest_hash: str, digest: dict, result: dict | None, error: str | None) -> int:
        with connect(self.settings.database_path, self.settings.sqlite_busy_timeout_ms) as db:
            cursor = db.execute("""INSERT INTO section_summaries(section, created_at, trigger, window_hours, model,
                digest_hash, digest_json, result_json, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (section, created_at, trigger, int(window_hours), model, digest_hash,
                 json.dumps(digest, ensure_ascii=False, default=str),
                 json.dumps(result, ensure_ascii=False) if result is not None else None, error))
            return int(cursor.lastrowid)

    def latest(self, section: str, successful_only: bool = False) -> dict | None:
        sql = "SELECT * FROM section_summaries WHERE section=?"
        if successful_only:
            sql += " AND result_json IS NOT NULL"
        with connect(self.settings.database_path, self.settings.sqlite_busy_timeout_ms, readonly=True) as db:
            row = db.execute(sql + " ORDER BY id DESC LIMIT 1", (section,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["result"] = json.loads(item["result_json"]) if item.get("result_json") else None
        return item
