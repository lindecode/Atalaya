"""How each evidence table is shown: Spanish labels, internal columns hidden, values formatted by kind.

The GUI keeps the raw row next to the displayed one, so selecting a row can still show every stored field.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from interfaces.gui.table_formatting import to_local_datetime


# Columns never worth a table cell: internal keys and payloads that belong in the row detail
HIDDEN = {"dedup_key", "raw_xml", "run_id"}

LOGON_TYPES = {2: "Interactivo", 3: "Red", 4: "Lote", 5: "Servicio", 7: "Desbloqueo", 8: "Red (texto claro)",
               9: "Credenciales nuevas", 10: "Remoto (RDP)", 11: "Interactivo en caché"}
FILE_ACTIONS = {"created": "Creado", "modified": "Modificado", "deleted": "Borrado", "moved": "Renombrado/movido",
                "observed_new": "Nuevo (escaneo)", "observed_changed": "Cambiado (escaneo)"}
PERSISTENCE_KINDS = {"run_key": "Clave Run", "startup_folder": "Carpeta Inicio", "scheduled_task": "Tarea programada",
                     "service": "Servicio"}
VERDICTS = {"malicious": "Malicioso", "suspicious": "Sospechoso", "likely_safe": "Probablemente seguro",
            "unknown": "Desconocido"}
EVENT_NAMES = {4624: "Inicio de sesión", 4625: "Inicio fallido", 4648: "Credenciales explícitas", 4672: "Privilegios especiales",
               4698: "Tarea programada creada", 4720: "Usuario creado", 4732: "Añadido a grupo", 1102: "Log de auditoría borrado",
               1149: "Conexión RDP"}
DIRECTIONS = {"inbound": "Entrante", "outbound": "Saliente", "listen": "En escucha"}


@dataclass(frozen=True)
class Column:
    source: str
    label: str
    kind: str = "text"            # text | int | date | bytes | percent | ratio | bool | json_list
    labels: Mapping[Any, str] | None = None
    help: str | None = None


VIEWS: dict[str, tuple[Column, ...]] = {
    "auth_events": (
        Column("ts", "Fecha", "date"), Column("event_id", "Evento", "event"), Column("target_user", "Cuenta"),
        Column("source_ip", "IP de origen"), Column("source_host", "Equipo de origen"),
        Column("logon_type", "Tipo de inicio", labels=LOGON_TYPES), Column("process_name", "Proceso"),
        Column("status_code", "Código"), Column("channel", "Canal")),
    "file_events": (
        Column("ts", "Fecha", "date"), Column("action", "Acción", labels=FILE_ACTIONS), Column("path", "Ruta"),
        Column("dest_path", "Destino"), Column("extension", "Extensión"), Column("size", "Tamaño", "bytes"),
        Column("sha256", "SHA-256"), Column("process_name", "Proceso"), Column("source", "Fuente")),
    "firewall_events": (
        Column("ts", "Fecha", "date"), Column("action", "Acción"), Column("proto", "Protocolo"),
        Column("src_ip", "IP de origen"), Column("src_port", "Puerto de origen", "int"), Column("dst_ip", "IP de destino"),
        Column("dst_port", "Puerto de destino", "int"), Column("direction", "Sentido")),
    "persistence_items": (
        Column("first_seen", "Vista por primera vez", "date"), Column("kind", "Tipo", labels=PERSISTENCE_KINDS),
        Column("name", "Nombre"), Column("location", "Ubicación"), Column("command", "Comando"),
        Column("active", "Activa", "bool"), Column("last_seen", "Última vez", "date"),
        Column("last_missing_at", "Desapareció", "date")),
    "file_reputation": (
        Column("checked_at", "Revisado", "date"), Column("verdict", "Veredicto", labels=VERDICTS),
        Column("confidence", "Confianza", "ratio"), Column("path", "Ruta"), Column("sha256", "SHA-256"),
        Column("provider", "Fuente externa"), Column("reasons_json", "Motivos", "json_list")),
    "ssh_observations": (
        Column("ts", "Fecha", "date"), Column("kind", "Tipo", labels={"session": "Sesión", "service": "Servicio"}),
        Column("direction", "Sentido", labels=DIRECTIONS), Column("remote_address", "Remoto"),
        Column("remote_port", "Puerto remoto", "int"), Column("local_address", "Local"),
        Column("local_port", "Puerto local", "int"), Column("state", "Estado"), Column("process_name", "Proceso"),
        Column("process_user", "Usuario"), Column("command_summary", "Comando"), Column("tunnel_types", "Túneles"),
        Column("agent_forwarding", "Reenvío de agente", "bool"), Column("service_status", "Estado del servicio"),
        Column("service_start_type", "Inicio del servicio"), Column("pid", "PID", "int")),
    "runs": (
        Column("id", "#", "int"), Column("kind", "Tipo"), Column("started_at", "Inicio", "date"),
        Column("finished_at", "Fin", "date"), Column("status", "Estado"), Column("is_admin", "Administrador", "bool")),
}


def _value(column: Column, value: Any) -> Any:
    if value is None:
        return None
    if column.kind == "date":
        return to_local_datetime(value)
    if column.kind == "event":
        return f"{EVENT_NAMES.get(value, 'Evento')} ({value})"
    if column.kind == "bool":
        return bool(value)
    if column.kind == "json_list":
        try:
            items = json.loads(value) if isinstance(value, str) else value
        except ValueError:
            return value
        return " · ".join(map(str, items)) if isinstance(items, list) else value
    if column.labels is not None:
        return column.labels.get(value, value)
    return value


def column_config(columns: Iterable[Column]) -> dict[str, Any]:
    import streamlit as st

    from interfaces.gui.table_formatting import COLUMN_FORMAT

    makers: dict[str, Callable[[Column], Any]] = {
        "date": lambda c: st.column_config.DatetimeColumn(c.label, format=COLUMN_FORMAT, help=c.help),
        "int": lambda c: st.column_config.NumberColumn(c.label, format="plain", help=c.help),
        "bytes": lambda c: st.column_config.NumberColumn(c.label, format="bytes", help=c.help),
        "percent": lambda c: st.column_config.ProgressColumn(c.label, format="%.1f%%", min_value=0, max_value=100,
                                                             help=c.help),
        "ratio": lambda c: st.column_config.ProgressColumn(c.label, format="percent", min_value=0, max_value=1,
                                                           help=c.help),
        "bool": lambda c: st.column_config.CheckboxColumn(c.label, help=c.help),
    }
    return {c.label: makers[c.kind](c) for c in columns if c.kind in makers}


def present(rows: Iterable[Mapping[str, Any]], view: str) -> list[dict[str, Any]]:
    columns = VIEWS[view]
    return [{column.label: _value(column, row.get(column.source)) for column in columns} for row in rows]


def visible(row: Mapping[str, Any]) -> dict[str, Any]:
    """Generic tables (no view): everything except internal columns."""
    return {key: value for key, value in row.items() if key not in HIDDEN}
