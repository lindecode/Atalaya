from __future__ import annotations

import ipaddress
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from domain.rules.catalog import ALL_RULES
from infrastructure.clock import SystemClock
from infrastructure.sqlite.queries import ENTITY_LIMIT, ROWS_LIMIT
from interfaces.gui import network
from interfaces.gui.common import AI_PAGE, ai_status, context, refresh_data, selected_window_hours
from interfaces.gui.components import (SEVERITY_COLORS, SEVERITY_ICONS, SEVERITY_NAMES, chart, empty, hero, legend,
                                       csv_name, page_link, plain_label, risk_banner, search_links, severity_label, table)
from interfaces.gui.chart_data import hourly_frame
from interfaces.gui.rule_help import OPEN_STATUSES, RULES, STATUS_NAMES, rule_help, status_names
from interfaces.gui.path_actions import path_actions
from interfaces.gui.safe_markdown import safe_markdown
from interfaces.gui.table_formatting import COLUMN_FORMAT, format_local_datetime, local_series, to_local_datetime
from interfaces.gui.table_views import EVENT_NAMES, FILE_ACTIONS, VIEWS, evidence_view
from shared.i18n import DEFAULT_LANGUAGE, t


LIVE_PAGE = "views/02_En_vivo.py"
HISTORY_PAGE = "views/20_Historial.py"
SETTINGS_PAGE = "views/32_Ajustes.py"
FLOW_LEGEND = [("Entrante", network.COLORS["inbound"]), ("Saliente", network.COLORS["outbound"]),
               ("Proceso local", network.COLORS["process"]), ("IP de Internet", network.COLORS["public"]),
               ("IP de red local/VPN", network.COLORS["private"]), ("Sospechosa", network.COLORS["suspicious"])]


def _local(ts: str | None) -> str:
    if not ts:
        return "nunca"
    return datetime.fromisoformat(ts).astimezone().strftime("%d/%m %H:%M")


_link = page_link


MEMORY_COLUMNS = {
    "memoria MB": st.column_config.NumberColumn(format="%.1f"), "privada MB": st.column_config.NumberColumn(format="%.1f"),
    "RSS MB": st.column_config.NumberColumn(format="%.1f"), "pico privado MB": st.column_config.NumberColumn(format="%.1f"),
    "% RAM": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
}


def _truncation_note(rows, limit: int = ROWS_LIMIT):
    """query.rows() stops at `limit`: say so, since the metrics and tables below are computed from those rows."""
    if len(rows) >= limit:
        st.warning(f"Se muestran las {limit:,} filas más recientes de la ventana; las cifras de esta página se "
                   "calculan sobre ellas. Elija una ventana temporal más corta para verlo todo.", icon=":material/info:")


HOUR_MS = 3_600_000


def _style(figure, height: int = 320):
    """Shared chart look: transparent background, legend below, compact hover."""
    figure.update_layout(height=height, margin=dict(l=8, r=8, t=10, b=8), paper_bgcolor="rgba(0,0,0,0)",
                         plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=-0.18, title=None),
                         hoverlabel=dict(namelength=-1), bargap=0.15)
    return figure


def _time_axis(figure, hourly_bars: bool = False):
    """Local-time axis as dd/mm HH:MM; hourly bars span their hour instead of a millisecond-wide sliver."""
    figure.update_xaxes(tickformat="%d/%m<br>%H:%M", hoverformat="%d/%m/%Y %H:%M", title=None)
    if hourly_bars:
        figure.update_traces(width=HOUR_MS * 0.85, selector=dict(type="bar"))
    return figure


# --- Resumen del LLM por sección -------------------------------------------------------------------

def _ago(ts: str, lang: str = "es") -> str:
    minutes = int((datetime.now().astimezone() - datetime.fromisoformat(ts).astimezone()).total_seconds() // 60)
    if lang == "en":
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes} min ago"
        return f"{minutes // 60} h ago" if minutes < 48 * 60 else f"{minutes // 1440} days ago"
    if minutes < 1:
        return "hace un momento"
    if minutes < 60:
        return f"hace {minutes} min"
    return f"hace {minutes // 60} h" if minutes < 48 * 60 else f"hace {minutes // 1440} días"


def _section_summary(query, settings, section: str):
    """Latest LLM summary of this section (automatic or on demand) and a button to refresh it now."""
    lang = st.session_state.get("language") or "es"
    found = query.latest_section_summary(section)
    latest, last = found["ok"], found["last"]
    with st.container(border=True):
        head, action = st.columns([3, 1], vertical_alignment="center")
        title_hdr = "**:material/psychology: " + ("LLM Summary" if lang == "en" else "Resumen del LLM") + "**"
        if latest:
            result = latest["result"]
            origin = ("automatic" if latest["trigger"] == "auto" else "on demand") if lang == "en" else ("automático" if latest["trigger"] == "auto" else "a petición")
            head.markdown(f"{title_hdr} · {_severity_name(result['risk'], lang=lang)}")
            win_desc = f"{latest['window_hours']}h window" if lang == "en" else f"ventana de {latest['window_hours']} h"
            head.caption(f"{_ago(latest['created_at'], lang=lang)} · {format_local_datetime(latest['created_at'])} · "
                         f"{_plain(latest['model'] or '?')} · {win_desc} · {origin}")
        else:
            head.markdown(title_hdr)
            head.caption("No summary for this section yet: the automated cycle generates one, or click «Summarize now»."
                         if lang == "en" else
                         "Aún no hay resumen de esta sección: el ciclo automático genera uno por turno, "
                         "o pulse «Resumir ahora».")
        btn_label = "Summarize now" if lang == "en" else "Resumir ahora"
        btn_help = ("Uses sidebar time window. Only runs one summary at a time." if lang == "en" else
                    "Usa la ventana temporal de la barra lateral. Solo corre un resumen a la vez.")
        if action.button(btn_label, key=f"summary-{section}", icon=":material/auto_awesome:", width="stretch",
                         help=btn_help):
            from bootstrap import build_section_summary_service
            spin_msg = "Local LLM is summarizing this section…" if lang == "en" else "El LLM local está resumiendo esta sección…"
            with st.spinner(spin_msg):
                try:
                    build_section_summary_service(settings).summarize(section, selected_window_hours(), "manual")
                except RuntimeError as exc:  # another summary holds the LLM
                    st.warning(str(exc))
                    return
            refresh_data()
            st.rerun()
        if latest:
            # LLM text is shaped by collected data: plain text, never Markdown/HTML
            st.text(latest["result"]["summary"])
            points = latest["result"].get("highlights", [])
            if points:
                st.text("\n".join(f"• {point}" for point in points))
            st.caption("Local LLM interpretation from aggregated figures; compare with the evidence on this page."
                       if lang == "en" else
                       "Interpretación del LLM local a partir de cifras agregadas; contrástela con la evidencia de esta página.")
        if last and last.get("error") and (not latest or last["id"] != latest["id"]):
            fail_msg = (f"Latest attempt ({_ago(last['created_at'], lang=lang)}) failed; showing previous summary."
                        if lang == "en" else
                        f"El último intento ({_ago(last['created_at'], lang=lang)}) falló; se muestra el resumen anterior.")
            st.caption(fail_msg)
            st.text(last["error"][:300])


# --- Panel -----------------------------------------------------------------------------------------

def overview():
    settings, _, query, since = context()
    lang = st.session_state.get("language") or "es"
    hero("🛡️ Panel de seguridad", "Qué pasa ahora en este equipo: alertas abiertas, tráfico de red y exposición.", page_key="overview", lang=lang)
    _section_summary(query, settings, "panel")
    severities = query.open_alerts_by_severity()
    analysis = query.latest_analysis()
    rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    worst = next((level for level in ("critical", "high", "medium", "low") if severities.get(level)), "low")
    llm_level = analysis["result_json"]["overall_risk"] if analysis and analysis.get("result_json") else "low"
    level = max(worst, llm_level, key=rank.get)
    open_total = sum(severities.values())
    banner_detail = (
        (f"{open_total} open alert(s)" + (" · based on rules and latest LLM analysis" if analysis and analysis.get("result_json") else ""))
        if lang == "en" else
        (f"{open_total} alerta(s) abierta(s)" + (" · según reglas y el último análisis del LLM" if analysis and analysis.get("result_json") else ""))
    )
    risk_banner(level, banner_detail, lang=lang)
    _live_health(query.live_runs(15))

    snapshot = query.connections(since, latest_only=True)
    flows = network.active_flows(snapshot)
    exposed = [item for item in network.exposure(snapshot) if item["alcance"] == "Toda la red"]
    a, b, c, d, e = st.columns(5)
    a.metric("Critical/high alerts" if lang == "en" else "Alertas críticas/altas", severities.get("critical", 0) + severities.get("high", 0))
    b.metric("Active outbound" if lang == "en" else "Salientes activas", sum(row["direction"] == "outbound" for row in flows))
    c.metric("Active inbound" if lang == "en" else "Entrantes activas", sum(row["direction"] == "inbound" for row in flows))
    d.metric("Network open ports" if lang == "en" else "Puertos abiertos a la red", len(exposed))
    e.metric("Distinct destinations" if lang == "en" else "Destinos distintos", len({row["raddr"] for row in flows if row["direction"] == "outbound"}))

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Current Traffic" if lang == "en" else "Tráfico ahora", divider="gray")
        if flows:
            legend(FLOW_LEGEND[:3])
            chart(network.flow_figure(network.build_flow(flows, max_remotes=8, suspicious_ports=settings.suspicious_ports), height=420),
                  key="overview-flow")
            _link("views/11_Conexiones.py", "View full connection map" if lang == "en" else "Ver el mapa completo de conexiones", ":material/hub:")
        else:
            empty("No active outbound connections in latest collection. Click Collect." if lang == "en" else "Sin conexiones activas con el exterior en la última recolección. Pulse Recolectar.")
    with right:
        st.subheader("Open Alerts" if lang == "en" else "Alertas abiertas", divider="gray")
        if severities:
            # A few categories compared by size: labelled bars read faster than a donut
            sev_label_fn = lambda s: t(f"tables.severity.{s}", lang=lang, default=SEVERITY_NAMES[s])
            frame = pd.DataFrame([{"nivel": sev_label_fn(s), "total": severities[s]}
                                  for s in ("low", "medium", "high", "critical") if severities.get(s)])
            figure = px.bar(frame, x="total", y="nivel", orientation="h", color="nivel", text="total",
                            color_discrete_map={sev_label_fn(s): c for s, c in SEVERITY_COLORS.items()},
                            labels={"nivel": "", "total": ""})
            figure.update_traces(textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{x}<extra></extra>")
            figure.update_xaxes(showticklabels=False, showgrid=False)
            chart(_style(figure, 50 + 42 * len(frame)).update_layout(showlegend=False), key="overview-severity")
            for alert in query.open_alerts(6):
                _link("views/03_Alertas.py", f"{_severity_name(alert['severity'], lang=lang)} · \\#{alert['id']} {alert['rule_id']} · "
                      f"{_plain(alert['title'])}", ":material/chevron_right:", query_params={"id": alert["id"]})
            _link("views/03_Alertas.py", "Review alerts" if lang == "en" else "Revisar alertas", ":material/notification_important:")
        else:
            st.success("No open alerts." if lang == "en" else "No hay alertas abiertas.")
        _link(HISTORY_PAGE, "LLM conclusions in history" if lang == "en" else "Conclusiones del LLM en el historial", ":material/history_edu:")

    st.subheader("Activity per Hour" if lang == "en" else "Actividad por hora", divider="gray")
    _activity_chart(query, since)



# --- Operaciones en vivo -------------------------------------------------------------------------

LIVE_TYPES = {"alerta": "🚨 Alertas", "conexión": "🌐 Conexiones", "acceso": "🔑 Accesos", "archivo": "📁 Archivos",
              "firewall": "🧱 Firewall", "ssh": "🖥️ SSH"}
LIVE_LEVELS = {"critical": "🔴 Crítico", "high": "🟠 Alto", "medium": "🟡 Atención", "low": "⚪ Bajo", "info": "· Info"}
LIVE_ORIGINS = {"outbound": "Saliente", "inbound": "Entrante", "listen": "En escucha", "session": "Sesión",
                "service": "Servicio", "DROP": "Bloqueado", "ALLOW": "Permitido", "scan": "Escaneo",
                "watchdog": "Vigilancia en vivo", **FILE_ACTIONS, **{str(key): value for key, value in EVENT_NAMES.items()}}
RUN_KINDS = {"collect": "Recolección", "analyze": "Análisis", "watch": "Vigilancia de archivos", "cycle": "Ciclo"}
RUN_STATES = {"ok": "✅ Correcta", "partial": "🟡 Parcial", "error": "❌ Error", "running": "🔄 En curso",
              "skipped": "⏭️ Omitida"}
COLLECTOR_NAMES = {
    "psutil_connections": "Conexiones de red", "psutil_processes": "Procesos", "security_events": "Accesos (Security)",
    "rdp_events": "Escritorio remoto (RDP)", "recent_files": "Archivos recientes", "windows_persistence": "Persistencia",
    "windows_firewall": "Firewall de Windows", "sysmon_network": "Sysmon · red", "sysmon_files": "Sysmon · archivos",
    "sysmon_process_registry": "Sysmon · procesos y registro", "ssh_observability": "SSH", "watchdog": "Vigilancia de archivos",
}
FRESHNESS = {"ok": ("Al día", "#22C55E"), "late": ("Con retraso", "#EAB308"), "stale": ("Desactualizada", "#EF4444"),
             "none": ("Sin revisar", "#94A3B8"), "off": ("No disponible", "#94A3B8")}
# Which collectors check each source; alerts are checked by every analysis
SOURCE_COLLECTORS = {
    "Procesos": ("psutil_processes",), "Conexiones": ("psutil_connections", "sysmon_network"),
    "Accesos": ("security_events", "rdp_events"), "Archivos": ("recent_files", "sysmon_files", "watchdog"),
    "Firewall": ("windows_firewall",), "SSH": ("ssh_observability",),
}


def _source_checks(runs: list[dict], last_data: dict[str, str | None]) -> list[tuple[str, str, str, str]]:
    """(source, state, 'revisada …', 'último dato …') per source: quiet sources are fine, unavailable ones say so."""
    rows = []
    for source in (*SOURCE_COLLECTORS, "Alertas"):
        data_age = _age_label(last_data.get(source))[0]
        data_text = "sin datos aún" if data_age == "Sin datos" else f"último dato {data_age}"
        if source == "Alertas":
            run = next((run for run in runs if run["kind"] == "analyze" and run["status"] != "running"), None)
        else:
            run = next((run for run in runs if run["status"] != "running"
                        and any(name in (run.get("collectors") or {}) for name in SOURCE_COLLECTORS[source])), None)
        if run is None:
            rows.append((source, "none", "no revisada recientemente", data_text))
            continue
        statuses = [run["collectors"][name].get("status") for name in SOURCE_COLLECTORS.get(source, ())
                    if name in (run.get("collectors") or {})]
        # Files are only scanned by the standard profile, which runs every N cycles
        interval = _cycle_config()[1] if source == "Archivos" else None
        checked, state = _age_label(run.get("finished_at") or run["started_at"], interval)
        if statuses and not any(status in {"ok", "partial"} for status in statuses):
            rows.append((source, "off", f"comprobada {checked}", "requiere permisos o no existe"))
        else:
            rows.append((source, state, f"revisada {checked}", data_text))
    return rows


def _seconds_since(value: str | None) -> int | None:
    if not value:
        return None
    observed = datetime.fromisoformat(value)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return max(0, int((datetime.now().astimezone() - observed.astimezone()).total_seconds()))


def _age_label(value: str | None, interval: int | None = None) -> tuple[str, str]:
    """('hace 3 min', state) with the state measured against how often that thing is expected (default: the cycle)."""
    seconds = _seconds_since(value)
    if seconds is None:
        return "Sin datos", "none"
    text = (f"hace {seconds} s" if seconds < 60 else f"hace {seconds // 60} min" if seconds < 3600
            else f"hace {seconds // 3600} h" if seconds < 172_800 else f"hace {seconds // 86_400} días")
    expected = interval or _cycle_seconds()
    return text, "ok" if seconds <= 2 * expected else "late" if seconds <= 6 * expected else "stale"


@st.cache_data(ttl=60, show_spinner=False)
def _cycle_config() -> tuple[int, int]:
    """(seconds between cycles, seconds between standard-profile cycles) from the automation settings."""
    from bootstrap import build_automation_config_service
    try:
        config = build_automation_config_service().load()
        return int(config.cycle_minutes) * 60, int(config.cycle_minutes * config.standard_every_cycles) * 60
    except Exception:
        return 300, 3600


def _cycle_seconds() -> int:
    return _cycle_config()[0]


def _live_health(runs: list[dict]):
    """One sentence that says whether Atalaya is watching, and what to do if it is not."""
    cycle_min = _cycle_seconds() // 60
    # File watching runs for hours and only beats when it saves events: it is not a collection in progress
    watch = next((run for run in runs if run["kind"] == "watch" and run["status"] == "running"), None)
    if watch:
        beat, _ = _age_label(watch.get("heartbeat_at") or watch["started_at"])
        st.caption(f":material/visibility: Vigilancia de archivos activa desde {format_local_datetime(watch['started_at'])}"
                   f" · último cambio registrado {beat}. Si sabe que hubo cambios y no aparecen, reinicie Atalaya.")
    current = next((run for run in runs if run["status"] == "running" and run["kind"] != "watch"), None)
    last_collect = next((run for run in runs if run["kind"] == "collect" and run["status"] != "running"), None)
    if current:
        beat, state = _age_label(current.get("heartbeat_at") or current["started_at"])
        if state == "stale":
            st.error(f"La {RUN_KINDS.get(current['kind'], current['kind']).lower()} #{current['id']} lleva sin dar "
                     f"señales desde {beat}: puede haberse quedado bloqueada. Revise la bitácora en Ajustes o reinicie Atalaya.",
                     icon=":material/error:")
        else:
            st.info(f"{RUN_KINDS.get(current['kind'], current['kind'])} en curso (#{current['id']}) · última señal {beat}.",
                    icon=":material/sync:")
        return
    if not last_collect:
        st.warning("Todavía no hay recolecciones. Pulse «Recolectar» en la barra lateral para tomar la primera foto del "
                   "equipo.", icon=":material/info:")
        return
    age, state = _age_label(last_collect.get("finished_at") or last_collect["started_at"])
    partial = " Algunas fuentes no estuvieron disponibles (ver detalle abajo)." if last_collect["status"] == "partial" else ""
    if state == "ok":
        st.success(f"Atalaya está vigilando: última recolección {age} (el ciclo automático corre cada {cycle_min} min)."
                   + partial, icon=":material/check_circle:")
    elif state == "late":
        st.warning(f"La última recolección fue {age}, más de lo esperado para un ciclo de {cycle_min} min." + partial,
                   icon=":material/schedule:")
    else:
        st.error(f"Sin recolecciones recientes: la última fue {age}. El ciclo automático no parece estar activo; "
                 "lo que ve abajo no es el estado actual. Pulse «Recolectar» en la barra lateral o active el "
                 "análisis periódico en Ajustes.", icon=":material/warning:")
        _link(SETTINGS_PAGE, "Activar el análisis periódico", ":material/toggle_on:")


def _live_event_links(row: dict):
    """From a selected event to the page that explains it."""
    kind, summary = row.get("tipo"), str(row.get("resumen") or "")
    if kind == "alerta":
        _link("views/03_Alertas.py", f"Abrir la alerta \\#{row['entidad_id']}", ":material/notification_important:",
              query_params={"id": row["entidad_id"]})
    address = summary.split("→")[-1].strip().rsplit(":", 1)[0] if "→" in summary else ""
    if kind in {"conexión", "ssh"} and _valid_ip(address):
        _link("views/11_Conexiones.py", f"Ver la IP {_valid_ip(address)} en Conexiones", ":material/hub:",
              query_params={"ip": _valid_ip(address)})
    term = _valid_ip(address) or (summary if kind == "archivo" else summary.split(" desde ")[-1])
    if term and len(term) >= 2:
        _link("views/10_Buscar.py", f"Buscar «{_plain(term[:60])}»", ":material/search:", query_params={"q": term[:200]})


def live_operations():
    _, _, query, since = context()
    lang = st.session_state.get("language") or "es"
    hero("⚡ En vivo", "¿Atalaya está vigilando ahora mismo? ¿Qué acaba de pasar? Se actualiza sola; no usa el LLM.", page_key="live", lang=lang)
    controls = st.columns([2, 2, 3], vertical_alignment="bottom")
    enabled = controls[0].toggle("Auto-refresh" if lang == "en" else "Actualización automática", value=True, key="live-enabled",
                                 help="Desactívela para examinar un evento sin que la lista se mueva." if lang != "en" else "Disable to inspect an event without moving the list.")
    seconds = controls[1].selectbox("Every" if lang == "en" else "Cada", [5, 10, 30, 60], index=1, key="live-seconds", disabled=not enabled,
                                    format_func=lambda value: f"{value} seconds" if lang == "en" else f"{value} segundos")
    controls[2].caption("Event stream uses sidebar time window; pulse uses last hour." if lang == "en" else "El flujo de eventos usa la ventana temporal de la barra lateral; el pulso, la última hora.")
    every = f"{seconds}s" if enabled else None

    @st.fragment(run_every=every)
    def current_state():
        runs = query.live_runs(15)
        _live_health(runs)
        status = query.live_status()
        b, c, d, e = st.columns(4)
        b.metric("Processes" if lang == "en" else "Procesos", status["processes"], help="Active processes in latest snapshot.")
        c.metric("Private memory" if lang == "en" else "Memoria privada", f"{status['memory_bytes'] / (1024 ** 3):.1f} GB")
        d.metric("Connections" if lang == "en" else "Conexiones", status["connections"])
        e.metric("Listening" if lang == "en" else "En escucha", status["listeners"])

        st.markdown("**Sources** · when each was last checked" if lang == "en" else "**Fuentes** · cuándo se revisó cada una por última vez")
        last_data = {row["fuente"]: row["ultima_observacion"] for row in query.live_freshness()}
        checks = _source_checks(runs, last_data)
        for column, (source, state, checked, data) in zip(st.columns(len(checks)), checks):
            label, color = FRESHNESS[state]
            column.markdown(f'<div class="nl-tile" style="--c:{color}"><span>{source}</span><b>{label}</b>'
                            f'<small>{checked}</small><small>{data}</small></div>', unsafe_allow_html=True)
        st.caption(f"«Al día»: revisada en los últimos 2 ciclos ({2 * _cycle_seconds() // 60} min); que no haya datos "
                   "nuevos es normal. «No disponible»: la fuente necesita permisos o no existe en este equipo "
                   f"(vea Primeros pasos). Archivos se revisa con el perfil standard, cada {_cycle_config()[1] // 60} min.")

        last_hour = max((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), since)
        pulse = query.live_activity(last_hour)
        if pulse:
            frame = pd.DataFrame(pulse)
            frame["minuto"] = local_series(frame["minuto"] + ":00+00:00")
            frame["tipo"] = frame["tipo"].map(LIVE_TYPES)
            figure = px.bar(frame, x="minuto", y="total", color="tipo", labels={"minuto": "", "total": "", "tipo": ""})
            figure.update_traces(width=60_000 * 0.8,
                                 hovertemplate="%{x|%d/%m %H:%M} · %{y} eventos<extra>%{fullData.name}</extra>")
            figure.update_xaxes(range=[to_local_datetime(last_hour), datetime.now()])
            st.markdown("**Last hour pulse** · events per minute" if lang == "en" else "**Pulso de la última hora** · eventos registrados por minuto (cada recolección aparece como un pico)")
            chart(_time_axis(_style(figure, 220)), key="live-pulse")

    current_state()

    st.subheader("What just happened" if lang == "en" else "Qué acaba de pasar", divider="gray")
    f1, f2, f3 = st.columns([3, 3, 2], vertical_alignment="bottom")
    types = f1.multiselect("Types" if lang == "en" else "Tipos", list(LIVE_TYPES), default=[name for name in LIVE_TYPES if name != "archivo"],
                           format_func=LIVE_TYPES.get, key="live-types", placeholder="All" if lang == "en" else "Todos",
                           help="Archivos se oculta por defecto: el escaneo genera miles de eventos." if lang != "en" else "Files are hidden by default: scans produce thousands of events.")
    text = f2.text_input("Buscar" if lang != "en" else "Search", key="live-text",
                         placeholder="IP, process, path, user…" if lang == "en" else "IP, proceso, ruta, usuario…",
                         icon=":material/search:")
    relevant = f3.toggle("Relevant only" if lang == "en" else "Solo lo relevante", key="live-relevant",
                         help="Oculta los eventos de nivel informativo." if lang != "en" else "Hides informational events.")


    @st.fragment(run_every=every)
    def recent_events():
        events = query.live_events(since, 300, types or list(LIVE_TYPES),
                                   text, relevant)
        if not events:
            return empty("No hay eventos con estos filtros en la ventana temporal elegida.")
        rows = [{**event, "Fecha": event["ts"], "Tipo": LIVE_TYPES.get(event["tipo"], event["tipo"]),
                 "Nivel": LIVE_LEVELS.get(event["nivel"], event["nivel"]),
                 "Qué pasó": (f"{FILE_ACTIONS.get(event['origen'], event['origen'])}: {event['resumen']}"
                              if event["tipo"] == "archivo" else event["resumen"]),
                 "Detalle": LIVE_ORIGINS.get(str(event["origen"]), event["origen"])} for event in events]
        st.caption(f"{len(rows)} evento(s), del más reciente al más antiguo"
                   + (" (máximo 300: acote con los filtros)." if len(rows) >= 300 else "."))
        shown = [{key: row[key] for key in ("Fecha", "Tipo", "Nivel", "Qué pasó", "Detalle")} for row in rows]
        table(shown, key="live-events", windowed=False, searchable=False,
              on_pick=lambda picked: _live_event_links(rows[shown.index(picked)] if picked in shown else picked))

    recent_events()

    with st.expander("Historial de ejecuciones y estado de cada recolector", icon=":material/history:"):
        runs = query.live_runs(15)
        if not runs:
            return empty("Todavía no hay ejecuciones registradas.")
        table([{"#": run["id"], "Tipo": RUN_KINDS.get(run["kind"], run["kind"]),
                "Estado": RUN_STATES.get(run["status"], run["status"]), "started_at": run["started_at"],
                "finished_at": run["finished_at"], "Administrador": bool(run["is_admin"])} for run in runs],
              key="live-runs", windowed=False, searchable=False, detail=False,
              columns={"started_at": st.column_config.DatetimeColumn("Inicio", format=COLUMN_FORMAT),
                       "finished_at": st.column_config.DatetimeColumn("Fin", format=COLUMN_FORMAT),
                       "#": st.column_config.NumberColumn(format="%d")})
        latest_collect = next((run for run in runs if run["kind"] == "collect" and run["collectors"]), None)
        if latest_collect:
            st.markdown(f"**Recolectores en la recolección #{latest_collect['id']}**")
            table([{"Recolector": COLLECTOR_NAMES.get(name, name),
                    "Estado": RUN_STATES.get(detail.get("status"), detail.get("status", "?")),
                    "Encontrados": detail.get("found", 0), "Nuevos": detail.get("inserted", 0),
                    "Avisos": "; ".join(map(str, detail.get("warnings", [])))[:300]}
                   for name, detail in latest_collect["collectors"].items()],
                  key="live-collectors", windowed=False, searchable=False, detail=False)


# --- Bitácora de errores -------------------------------------------------------------------------

def _error_log():
    """Technical log of Atalaya itself (shown as a tab of Ajustes)."""
    from infrastructure.log_reader import read_application_logs
    from infrastructure.logging_config import logs_dir

    directory = logs_dir()
    entries = read_application_logs(directory, 1000)
    levels = st.multiselect("Niveles", ["CRITICAL", "ERROR", "WARNING", "INFO"],
                            default=["CRITICAL", "ERROR", "WARNING"], key="log-levels")
    search = st.text_input("Buscar", placeholder="Componente, mensaje o tipo de error", key="log-search",
                           icon=":material/search:").casefold().strip()
    visible = [entry for entry in entries if entry.get("level") in levels and
               (not search or search in " ".join(str(value) for value in entry.values()).casefold())]

    a, b, c = st.columns(3)
    a.metric("Errores visibles", sum(entry.get("level") in {"ERROR", "CRITICAL"} for entry in visible))
    b.metric("Advertencias visibles", sum(entry.get("level") == "WARNING" for entry in visible))
    c.metric("Entradas cargadas", len(entries))
    st.caption(f"Carpeta: {directory} · cada componente conserva hasta cinco archivos de 5 MB. "
               "Tokens y contraseñas reconocibles se redactan.")
    if not visible:
        return empty("No hay entradas que coincidan con los filtros.")

    rows = [{"Fecha": item.get("ts"), "Nivel": item.get("level"), "Componente": item.get("logger"),
             "Mensaje": item.get("message"), "Proceso": item.get("process")} for item in visible]
    table(rows, key="error-log", windowed=False, searchable=False, detail=False,
          columns={"Fecha": st.column_config.DatetimeColumn(format=COLUMN_FORMAT)})
    with st.expander("Trazas de excepciones"):
        failures = [item for item in visible if item.get("exception")]
        if not failures:
            st.caption("Las entradas visibles no contienen trazas.")
        for index, item in enumerate(failures[:50]):
            st.text(f"{format_local_datetime(item.get('ts'))} · {item.get('logger')} · {item.get('message')}")
            st.code(str(item["exception"]), language="text")
            if index < len(failures[:50]) - 1:
                st.divider()


# --- Actividad (antes Resumen) ---------------------------------------------------------------------

def _activity_chart(query, since: str):
    """Events per hour, one row per type with its own scale (connections would otherwise flatten the alerts)."""
    timeline = query.timeline(since)
    if not timeline:
        return empty("Recolecte datos para ver la actividad por hora.")
    frame = hourly_frame(timeline, since, time_key="bucket", value_key="count", series_key="type")
    figure = px.bar(frame, x="bucket", y="count", color="type", facet_row="type",
                    labels={"bucket": "", "count": "", "type": ""})
    figure.update_yaxes(matches=None, title=None)
    figure.for_each_annotation(lambda note: note.update(text=note.text.split("=")[-1].capitalize(), textangle=0,
                                                        x=0, xanchor="left", y=note.y + 0.02, yanchor="bottom"))
    figure.update_traces(hovertemplate="%{x|%d/%m %H:%M} · %{y} eventos<extra>%{fullData.name}</extra>")
    types = frame["type"].nunique()
    chart(_time_axis(_style(figure, 70 + 110 * types), hourly_bars=True).update_layout(showlegend=False),
          key="activity-timeline")


@st.cache_data(ttl=120, show_spinner=False)
def _dns_records() -> list[dict]:
    from infrastructure.windows.dns_cache import dns_cache_records
    return dns_cache_records()


def _valid_ip(text: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address(str(text or "").strip().split("%")[0]))
    except ValueError:
        return None


def _ip_matches(row: dict, needle: str) -> bool:
    return any(needle in str(row.get(field) or "") for field in ("raddr", "laddr"))


def _ip_profile(query, ip: str, since: str, key: str = "profile"):
    """What this computer knows about one IP: names (history, label, reverse DNS), scope, processes, ports, evidence."""
    from infrastructure.windows.dns_cache import names_for

    lang = st.session_state.get("language") or "es"
    tr = lambda es, en: en if lang == "en" else es
    found = query.entity_search(ip, since)
    exact = lambda rows, *fields: [row for row in rows if any(str(row.get(field) or "") == ip for field in fields)]
    conns = exact(found["connections"], "raddr", "laddr")
    blocked = exact(found["firewall_events"], "src_ip", "dst_ip")
    logons = exact(found["auth_events"], "source_ip")
    ssh = exact(found["ssh_observations"], "remote_address", "local_address")
    alerts = [row for row in found["alerts"] if f'"{ip}"' in str(row.get("evidence") or "") or ip == str(row.get("title"))]
    entry = query.ip_names([ip]).get(ip, {"label": None, "names": []})
    live = [name for name in names_for(ip, _dns_records()) if name not in {item["name"] for item in entry["names"]}]
    with st.container(border=True):
        # `ip` went through ipaddress.ip_address: only digits, hex, dots and colons reach the Markdown
        title = f"#### :material/lan: {ip} · {network.SCOPE_LABELS.get(network.scope(ip), 'Desconocido')}"
        st.markdown(title + (f" · {_plain(entry['label'])}" if entry["label"] else ""))
        known = [(item["name"], network.NAME_SOURCES.get(item["source"], item["source"]), item["last_seen"])
                 for item in entry["names"]] + [(name, network.NAME_SOURCES["dns_cache"], None) for name in live]
        if known:
            st.text(tr("Nombres conocidos: ", "Known names: ")
                    + ", ".join(f"{name} ({source})" for name, source, _ in known[:8])
                    + (f" (+{len(known) - 8})" if len(known) > 8 else ""))
        else:
            st.caption(tr("Sin nombres guardados: nadie en este equipo resolvió esta IP mientras Atalaya recolectaba.",
                          "No stored names: nothing on this computer resolved this IP while Atalaya was collecting."))
        a, b, c, d, e = st.columns(5)
        a.metric(tr("Conexiones", "Connections"), len(conns))
        b.metric(tr("Procesos", "Processes"), len({network.process_label(row) for row in conns}))
        c.metric(tr("Bloqueos del firewall", "Firewall blocks"), len(blocked))
        d.metric(tr("Inicios de sesión", "Logons"), len(logons))
        e.metric(tr("Alertas", "Alerts"), len(alerts))
        if conns:
            ports = sorted({row.get("rport") if row.get("raddr") == ip else row.get("lport") for row in conns} - {None})
            seen = sorted(str(row["ts"]) for row in conns)
            st.text(tr("Procesos: ", "Processes: ") + ", ".join(sorted({network.process_label(row) for row in conns}))[:400])
            st.text(tr("Puertos y servicios: ", "Ports and services: ")
                    + ", ".join(f"{port} ({network.service(port)})" for port in ports[:15]))
            st.text(tr(f"Primera vez: {format_local_datetime(seen[0])} · última vez: {format_local_datetime(seen[-1])} "
                       "(en la ventana temporal)", f"First seen: {format_local_datetime(seen[0])} · last seen: "
                       f"{format_local_datetime(seen[-1])} (within the time window)"))
        if ssh:
            st.text(tr(f"SSH: {len(ssh)} observación(es) con esta IP.", f"SSH: {len(ssh)} observation(s) with this IP."))
        for alert in alerts[:5]:
            _link("views/03_Alertas.py", f"{_severity_name(alert['severity'])} · alerta \\#{alert['id']} · {alert['rule_id']} · "
                  f"{_plain(alert['title'])}", ":material/notification_important:", query_params={"id": alert["id"]})
        _link("views/10_Buscar.py", tr(f"Ver todo lo registrado sobre {ip}", f"Everything recorded about {ip}"),
              ":material/search:", query_params={"q": ip})

        label_col, button_col = st.columns([3, 1], vertical_alignment="bottom")
        label = label_col.text_input(tr("Etiqueta para esta IP", "Label for this IP"), value=entry["label"] or "",
                                     max_chars=80, key=f"label-{key}-{ip}",
                                     placeholder=tr("Router de casa, NAS, Oficina…", "Home router, NAS, Office…"),
                                     help=tr("Se guarda en este equipo y se muestra en todas las tablas.",
                                             "Stored on this computer and shown in every table."))
        if button_col.button(tr("Guardar etiqueta", "Save label"), key=f"label-save-{key}-{ip}", width="stretch",
                             icon=":material/label:"):
            from bootstrap import build_repository
            build_repository().set_ip_label(ip, label, SystemClock().now_iso())
            refresh_data()
            st.rerun()
        with st.expander(tr("Consultar el nombre por DNS inverso", "Look up the name by reverse DNS"),
                         icon=":material/travel_explore:"):
            st.caption(tr("Envía esta IP a su servidor DNS (normalmente el router o su proveedor): sale del equipo. "
                          "Solo se consulta al pulsar.", "Sends this IP to your DNS server (usually the router or your "
                          "provider): it leaves the computer. It only runs when you click."))
            if st.button(tr("Consultar ahora", "Look up now"), key=f"rdns-{key}-{ip}", icon=":material/dns:"):
                from bootstrap import build_repository
                from infrastructure.windows.ip_names import reverse_lookup
                try:
                    found_names = reverse_lookup(ip)
                except (TimeoutError, OSError, ValueError) as exc:
                    st.warning(str(exc))
                else:
                    if found_names:
                        build_repository().save_ip_names(ip, found_names, "reverse_dns", SystemClock().now_iso())
                        refresh_data()
                        st.success(tr("Encontrado: ", "Found: ") + plain_label(", ".join(found_names)))
                    else:
                        st.info(tr("El servidor DNS no tiene un nombre para esta IP.",
                                   "The DNS server has no name for this IP."))


# --- Conexiones ------------------------------------------------------------------------------------

def connections():
    settings, _, query, since = context()
    lang = st.session_state.get("language") or "es"
    tr = lambda es, en: en if lang == "en" else es
    hero("🌐 Conexiones", "Quién habla con este equipo (entrantes), con quién habla él (salientes) y qué puertos deja abiertos.", page_key="connections", lang=lang)
    _section_summary(query, settings, "conexiones")
    controls = st.columns([2, 1, 1, 1])
    mode = controls[0].segmented_control(tr("Datos", "Data"), [tr("Última recolección", "Latest collection"),
                                                                tr("Toda la ventana", "Entire window")],
                                         default=tr("Última recolección", "Latest collection"), key="net-mode")
    direction = controls[1].selectbox(tr("Sentido", "Direction"), [tr("Ambos", "Both"), tr("Entrantes", "Inbound"),
                                                                    tr("Salientes", "Outbound")], key="net-direction")
    include_loopback = controls[2].toggle(tr("Tráfico interno", "Internal traffic"), value=False, key="net-loopback",
                                          help=tr("Conexiones entre programas del propio equipo (127.0.0.1)",
                                                  "Loopback traffic between local applications (127.0.0.1)"))
    include_closing = controls[3].toggle(tr("Cerrándose", "Closing"), value=False, key="net-closing",
                                         help=tr("Incluye TIME_WAIT, CLOSE_WAIT y similares", "Includes TIME_WAIT, CLOSE_WAIT, etc."))
    ip_filter = st.text_input(tr("Filtrar por IP", "Filter by IP"), value=st.query_params.get("ip", ""),
                              icon=":material/filter_alt:",
                              placeholder=tr("Una IP completa (203.0.113.7) o parte de ella (192.168.)", "203.0.113.7 · 192.168."),
                              help=tr("Filtra todas las pestañas por IP remota o local. Con una IP completa se muestra su perfil.",
                                      "Filters every tab by remote or local IP. A full IP opens its profile."))
    needle = ip_filter.strip()
    if needle != st.query_params.get("ip", ""):
        if needle:
            st.query_params["ip"] = needle
        elif "ip" in st.query_params:
            del st.query_params["ip"]
    entire_window = mode == tr("Toda la ventana", "Entire window")
    rows = query.connections(since, latest_only=not entire_window)
    if needle:
        total = len(rows)
        rows = [row for row in rows if _ip_matches(row, needle)]
        st.caption(tr(f"Filtrando por «{_plain(needle)}»: {len(rows)} de {total} conexiones.",
                      f"Filtering by «{_plain(needle)}»: {len(rows)} of {total} connections."))
    if _valid_ip(needle):
        _ip_profile(query, _valid_ip(needle), since, key="filter")
    names = network.name_map(query.ip_names())
    directory = query.ip_directory(since)
    servers = network.server_rows(query.servers(since))
    flows = network.active_flows(rows, include_loopback, include_closing)
    if direction != tr("Ambos", "Both"):
        wanted = "inbound" if direction == tr("Entrantes", "Inbound") else "outbound"
        flows = [row for row in flows if row["direction"] == wanted]
    suspicious = [row for row in flows if network.is_suspicious(row, settings.suspicious_ports)]

    named = sum(row["ip"] in names for row in directory)
    a, b, c, d, e = st.columns(5)
    a.metric(tr("Salientes", "Outbound"), sum(row["direction"] == "outbound" for row in flows))
    b.metric(tr("Entrantes", "Inbound"), sum(row["direction"] == "inbound" for row in flows))
    c.metric(tr("Puertos abiertos a la red", "Ports open to the network"),
             sum(row["alcance"] == "Toda la red" for row in servers),
             help=tr("Servidores que aceptan conexiones de cualquier equipo de la red, en la ventana.",
                     "Servers accepting connections from any host on the network, within the window."))
    d.metric(tr("IPs remotas", "Remote IPs"), len(directory),
             help=tr(f"{named} con nombre ({named * 100 // max(len(directory), 1)} %).",
                     f"{named} with a name ({named * 100 // max(len(directory), 1)}%)."))
    e.metric(tr("Sospechosas", "Suspicious"), len(suspicious))

    tab_flow, tab_servers, tab_ips, tab_time, tab_table = st.tabs([
        ":material/hub: " + tr("Mapa", "Map"), ":material/dns: " + tr("Servidores", "Servers"),
        ":material/contacts: " + "IPs", ":material/timeline: " + tr("Evolución", "Timeline"),
        ":material/table: " + tr("Detalle", "Details")])

    with tab_flow:
        if flows:
            legend(FLOW_LEGEND)
            top = st.slider(tr("IPs remotas por sentido", "Remote IPs per direction"), 4, 30, 12, key="net-top")
            flow = network.build_flow(flows, max_remotes=top, suspicious_ports=settings.suspicious_ports, names=names)
            chart(network.flow_figure(flow, height=max(460, 22 * len(flow.labels))), key="net-flow")
            st.caption(tr("El grosor de cada banda es el número de conexiones. Las IP que no entran en el top se agrupan en "
                          "«Otros». Pase el ratón por una banda para ver puertos y servicios.",
                          "Band width is the number of connections; IPs outside the top are grouped as «Others». "
                          "Hover a band for ports and services."))
        else:
            empty(tr("No hay conversaciones con esos filtros. Pruebe a activar «Tráfico interno» o «Toda la ventana».",
                     "No conversations with these filters. Try «Internal traffic» or «Entire window»."))

    with tab_servers:
        _servers_tab(query, servers, names, since, tr)

    with tab_ips:
        _ips_tab(query, directory, names, flows, since, tr)

    with tab_time:
        all_rows = query.connections(since) if not entire_window else rows
        if needle:
            all_rows = [row for row in all_rows if _ip_matches(row, needle)]
        points = network.timeline_rows(all_rows, include_loopback)
        if len({point["ts"] for point in points}) > 1:
            frame = pd.DataFrame(points)
            frame["ts"] = local_series(frame["ts"])
            figure = px.area(frame, x="ts", y="conexiones", color="sentido", markers=True,
                             color_discrete_map={"Entrantes": network.COLORS["inbound"], "Salientes": network.COLORS["outbound"]},
                             labels={"ts": "", "conexiones": tr("conexiones abiertas", "open connections"), "sentido": ""})
            chart(_time_axis(_style(figure, 360)), key="net-timeline")
            st.caption(tr("Cada punto es una recolección. Un salto brusco de salientes merece una mirada al mapa.",
                          "Each point is one collection. A sudden jump in outbound deserves a look at the map."))
        else:
            empty(tr("Hace falta más de una recolección en la ventana para ver la evolución.",
                     "More than one collection in the window is needed to see the timeline."))

    with tab_table:
        detail = [{"sentido": {"inbound": tr("⬅ entrante", "⬅ inbound"), "outbound": tr("➡ saliente", "➡ outbound")}[row["direction"]],
                   "proceso": network.process_label(row), "remoto": row["raddr"], "nombre": names.get(row["raddr"]),
                   "puerto remoto": row.get("rport"),
                   "servicio": network.service(row.get("rport") if row["direction"] == "outbound" else row.get("lport")),
                   "alcance": network.SCOPE_LABELS.get(network.scope(row["raddr"]), "?"), "local": f"{row.get('laddr')}:{row.get('lport')}",
                   "estado": row.get("state"), "sospechosa": "⚠" if network.is_suspicious(row, settings.suspicious_ports) else "",
                   "ruta": row.get("process_path"), "hora": row.get("ts")} for row in flows]
        st.caption(tr("Seleccione una conexión para ver el perfil de su IP remota.",
                      "Select a connection to see the profile of its remote IP."))
        table(detail, key="connections",
              on_pick=lambda row: _valid_ip(row.get("remoto")) and _ip_profile(query, _valid_ip(row["remoto"]), since, key="pick"))

    with st.expander(tr("Sesiones y agentes SSH", "SSH sessions and agents"), icon=":material/terminal:"):
        ssh_rows = query.rows("ssh_observations", since, 1000)
        if ssh_rows:
            sessions = [row for row in ssh_rows if row["kind"] == "session"]
            services = [row for row in ssh_rows if row["kind"] == "service"]
            a, b, c = st.columns(3)
            a.metric(tr("Sesiones observadas", "Observed sessions"), len(sessions))
            b.metric(tr("Túneles", "Tunnels"), sum(bool(row.get("tunnel_types")) for row in sessions))
            c.metric(tr("Reenvío de agente", "Agent forwarding"), sum(row.get("agent_forwarding") == 1 for row in sessions))
            table(services + sessions, key="ssh_observations", view="ssh_observations")
        else:
            st.caption(tr("Sin observaciones SSH. Pulse Recolectar para consultar sesiones, sshd y ssh-agent.",
                          "No SSH observations. Click Collect to check sessions, sshd and ssh-agent."))


REACH_ICONS = {"Toda la red": "🔴", "Una interfaz (LAN/VPN)": "🟠", "Solo este equipo": "⚪"}
REACH_EN = {"Toda la red": "Entire network", "Una interfaz (LAN/VPN)": "One interface (LAN/VPN)",
            "Solo este equipo": "This computer only"}


def _servers_tab(query, servers: list[dict], names: dict, since: str, tr):
    if not servers:
        return empty(tr("No hay puertos en escucha en la ventana.", "No listening ports in the window."))
    reaches = list(REACH_ICONS)
    network_open = [row for row in servers if row["alcance"] == "Toda la red"]
    external = sum(row["clientes_internet"] + row["clientes_red_local"] for row in servers)
    st.markdown(tr(f"**{len(servers)} puertos abiertos** · {len(network_open)} a toda la red · "
                   f"{external} cliente(s) de fuera de este equipo",
                   f"**{len(servers)} open ports** · {len(network_open)} to the whole network · "
                   f"{external} client(s) from outside this computer"))
    attention = [row for row in servers if row["atencion"]]
    if attention:
        st.error(tr(f"{len(attention)} servidor(es) abiertos a toda la red recibieron clientes de Internet: revíselos "
                    "primero.", f"{len(attention)} server(s) open to the whole network received Internet clients: "
                    "review them first."), icon=":material/public:")
    a, b, c = st.columns([3, 1, 1], vertical_alignment="bottom")
    chosen = a.multiselect(tr("Alcance", "Reach"), reaches, default=reaches[:2], key="servers-reach",
                           format_func=lambda reach: f"{REACH_ICONS[reach]} " + tr(reach, REACH_EN[reach]),
                           placeholder=tr("Todos", "All"),
                           help=tr("«Solo este equipo» son servicios internos de los programas; se ocultan por defecto.",
                                   "«This computer only» are programs' internal services; hidden by default."))
    with_clients = b.toggle(tr("Solo con clientes", "Only with clients"), key="servers-clients")
    only_new = c.toggle(tr("Solo nuevos", "Only new"), key="servers-new",
                        help=tr("No aprobados en la baseline.", "Not approved in the baseline."))
    shown = [row for row in servers if (not chosen or row["alcance"] in chosen)
             and (not with_clients or row["clients"]) and (not only_new or not row["aprobado"])]
    table_rows = [{"Atención": "🔴 " + tr("Clientes de Internet", "Internet clients") if row["atencion"] else "",
                   "Puerto": row["puerto"], "Protocolo": row["protocolo"], "Servicio": row["servicio"],
                   "Proceso": row["proceso"], "Alcance": f"{REACH_ICONS[row['alcance']]} " + tr(row["alcance"], REACH_EN[row["alcance"]]),
                   "Clientes de Internet": row["clientes_internet"], "Clientes de la red local": row["clientes_red_local"],
                   "Clientes de este equipo": row["clientes_locales"], "Conexiones ahora": row["conexiones_ahora"],
                   "Último cliente": row["ultimo_cliente"], "Visto por primera vez": row["first_seen"],
                   "Estado": tr("Aprobado", "Approved") if row["aprobado"] else tr("Nuevo", "New"),
                   "Ruta": row["ruta"]} for row in shown]
    st.caption(tr("Seleccione un servidor para ver quién se conectó a él.", "Select a server to see who connected to it."))
    by_key = {(row["puerto"], row["protocolo"], row["proceso"]): row for row in shown}

    def clients_of(picked: dict):
        server = by_key.get((picked.get("Puerto"), picked.get("Protocolo"), picked.get("Proceso")))
        if not server:
            return
        process = _plain(server["proceso"])  # collected text: escaped before it reaches Markdown
        st.markdown(tr(f"**Clientes de {process} en el puerto {server['puerto']}**",
                       f"**Clients of {process} on port {server['puerto']}**"))
        if not server["clients"]:
            return st.caption(tr("Nadie se conectó a este servidor en la ventana.",
                                 "Nobody connected to this server in the window."))
        rows = [{"IP": client["raddr"], "Nombre": names.get(client["raddr"]),
                 "Origen": network.SCOPE_LABELS.get(network.scope(client["raddr"]), "?"),
                 "Observaciones": client["observations"], "Primera vez": client["first_seen"],
                 "Última vez": client["last_seen"]} for client in server["clients"]]
        table(rows, key=f"server-clients-{server['protocolo']}-{server['puerto']}", windowed=True, searchable=False,
              dates=("Primera vez", "Última vez"),
              on_pick=lambda client: _valid_ip(client.get("IP")) and _ip_profile(query, _valid_ip(client["IP"]), since,
                                                                                  key="server"))

    table(table_rows, key="servers", columns={"Puerto": st.column_config.NumberColumn(format="%d")}, on_pick=clients_of,
          dates=("Último cliente", "Visto por primera vez"))


def _ips_tab(query, directory: list[dict], names: dict, flows: list[dict], since: str, tr):
    if not directory:
        return empty(tr("No hay IPs remotas en la ventana.", "No remote IPs in the window."))
    entries = query.ip_names([row["ip"] for row in directory])
    named = sum(row["ip"] in names for row in directory)
    left, right = st.columns([3, 2])
    with left:
        outbound = [row for row in flows if row["direction"] == "outbound"]
        if outbound:
            st.markdown(tr("**Servicios a los que se conecta el equipo**", "**Services this computer connects to**"))
            chart(network.destinations_figure(outbound), key="net-services")
    with right:
        st.markdown(tr("**Nombres**", "**Names**"))
        st.metric(tr("IPs con nombre", "IPs with a name"), f"{named} / {len(directory)}")
        st.caption(tr("Los nombres salen de la caché DNS de Windows (guardada en cada recolección), del archivo hosts, "
                      "de sus etiquetas y, si lo pide en el perfil de una IP, del DNS inverso.",
                      "Names come from the Windows DNS cache (saved on every collection), the hosts file, your labels "
                      "and, when you ask in an IP profile, reverse DNS."))
    rows = []
    for row in directory:
        name, source = network.best_name(entries.get(row["ip"]))
        ports = row["ports"]
        rows.append({"IP": row["ip"], "Nombre": name, "Origen del nombre": network.NAME_SOURCES.get(source) if source else None,
                     "Alcance": network.SCOPE_LABELS.get(network.scope(row["ip"]), "?"),
                     "Sentido": " · ".join({"inbound": tr("entrante", "inbound"), "outbound": tr("saliente", "outbound")}
                                           .get(item, item) for item in row["directions"]),
                     "Procesos": ", ".join(row["processes"][:3]) + (f" (+{len(row['processes']) - 3})"
                                                                   if len(row["processes"]) > 3 else ""),
                     "Puertos": ", ".join(f"{port} {network.service(int(port))}" if port.isdigit() else port
                                          for port in ports[:4]) + (f" (+{len(ports) - 4})" if len(ports) > 4 else ""),
                     "Observaciones": row["observations"], "Primera vez": row["first_seen"], "Última vez": row["last_seen"],
                     "Bloqueos FW": row["firewall_blocks"]})
    st.caption(tr("Busque por IP, nombre, proceso o servicio. Seleccione una IP para ver su perfil, etiquetarla o "
                  "consultar su nombre.", "Search by IP, name, process or service. Select an IP to see its profile, "
                  "label it or look up its name."))
    table(rows, key="ip-directory", dates=("Primera vez", "Última vez"),
          on_pick=lambda picked: _valid_ip(picked.get("IP")) and _ip_profile(query, _valid_ip(picked["IP"]), since,
                                                                              key="directory"))


# --- Alertas ---------------------------------------------------------------------------------------

MAX_ALERTS_SHOWN = 100
BASELINE_RULES = {"R03", "R04", "R05", "R06", "R07", "R10", "R17", "R18", "R20"}


def _bulk_learn(repository):
    with st.expander("Aprender baseline (reducir falsos positivos)", icon=":material/school:"):
        st.write("Aprueba como normal todo lo observado hasta ahora (puertos en escucha, orígenes de inicio de sesión, "
                 "servicios, tareas y claves Run) y descarta las alertas abiertas que eso cubre. Hágalo solo si confía "
                 "en el estado actual del equipo: lo que ya estuviera comprometido también quedaría aprobado.")
        sure = st.checkbox("Confío en el estado actual del equipo", key="learn-confirm")
        if st.button("Aprobar todo lo observado", disabled=not sure, key="learn"):
            now = SystemClock().now_iso()
            counts = repository.approve_all_observed(now)
            dismissed = repository.dismiss_baselined("Baseline aprendida", now)
            refresh_data()
            st.success(f"Aprobados {sum(counts.values())} elementos {counts}; {dismissed} alertas descartadas.")


def _alert_summary(evidence) -> str:
    """The rule's evidence summary as one line (collected values: shown in a dataframe cell, never as markup)."""
    try:
        data = json.loads(evidence) if isinstance(evidence, str) else evidence
    except ValueError:
        return str(evidence)[:200]
    if isinstance(data, dict):
        return " · ".join(f"{key}: {value}" for key, value in data.items())[:200]
    return str(data)[:200]


def _severity_name(level: str, lang: str | None = None) -> str:
    if lang is None:
        lang = st.session_state.get("language") or "es"
    sev = t(f"tables.severity.{level}", lang=lang, default=SEVERITY_NAMES.get(level, level))
    return f"{SEVERITY_ICONS.get(level, '⚪')} {sev}"


def _set_status(repository, alert_ids, status: str, note: str | None):
    now = SystemClock().now_iso()
    for alert_id in alert_ids:
        repository.update_alert_status(alert_id, status, note or None, now)
    refresh_data()


def _alert_detail(repository, query, row: dict, key_prefix: str = "alert"):
    """Everything about one alert: what the rule means, its evidence, the LLM's view and the triage actions."""
    with st.container(border=True):
        st.markdown(f"#### {_severity_name(row['severity'])} · {row['rule_id']} · alerta #{row['id']}")
        st.text(f"{row['title']}  ·  {STATUS_NAMES.get(row['status'], row['status'])}  ·  "
                f"{format_local_datetime(row['ts'])}")
        if row.get("status_note"):
            st.text(f"Nota: {row['status_note']}")
        from interfaces.gui.rule_help import rule_help
        lang = st.session_state.get("language") or "es"
        rule = rule_help(row["rule_id"], lang=lang)
        if rule:
            left, right = st.columns(2)
            left.markdown("**What it detects**" if lang == "en" else "**Qué detecta**")
            left.write(rule.detects)
            right.markdown("**What to check**" if lang == "en" else "**Qué revisar**")
            right.write(rule.check)
        try:
            summary = json.loads(row["evidence"]) if isinstance(row["evidence"], str) else row["evidence"]
        except ValueError:
            summary = {"evidencia": row["evidence"]}
        if isinstance(summary, dict) and summary:
            st.markdown("**Resumen de la evidencia**")
            st.dataframe(pd.DataFrame([{"campo": key, "valor": "" if value is None else str(value)}
                                       for key, value in summary.items()]), hide_index=True, width="stretch",
                         key=f"summary-{key_prefix}-{row['id']}")
            search_links(summary.values(), key=f"alert-{key_prefix}-{row['id']}")
        st.markdown("**Eventos que la originaron**")
        evidence = query.alert_evidence(row["id"])
        table(evidence, key=f"evidence-{key_prefix}-{row['id']}", view=evidence_view(evidence), windowed=False,
              on_pick=lambda record: path_actions(record, f"alert-{key_prefix}-{row['id']}", lang))
        for incident in query.llm_incidents_for(row["id"]):
            st.markdown(f"**Análisis del LLM** ({_plain(incident['model'])}) · severidad LLM: `{incident['severity']}` · "
                        f"posible falso positivo: `{incident['false_positive_likelihood']}`")
            # LLM text is shaped by collected data: show it as plain text, never as Markdown/HTML
            st.text(incident["narrative"])
            if incident.get("benign_explanations"):
                st.text("Explicaciones benignas: " + "; ".join(incident["benign_explanations"]))
            if incident.get("recommended_actions"):
                st.text("Recomendaciones: " + "; ".join(incident["recommended_actions"]))
        note = st.text_input("Nota", key=f"note-{key_prefix}-{row['id']}")
        a, b, c = st.columns(3)
        if a.button("Confirmar" if lang != "en" else "Confirm", key=f"confirm-{key_prefix}-{row['id']}", icon=":material/check_circle:"):
            _set_status(repository, [row["id"]], "confirmed", note); st.rerun()
        if row["status"] == "dismissed":
            reactivate_lbl = t("alerts.reactivate_btn", lang=lang, default="Reactivar alerta")
            if b.button(reactivate_lbl, key=f"reactivate-{key_prefix}-{row['id']}", icon=":material/replay:"):
                _set_status(repository, [row["id"]], "new", note or t("alerts.reactivated_note", lang=lang, default="Reactivada manualmente"))
                st.rerun()
        else:
            if b.button("Descartar" if lang != "en" else "Dismiss", key=f"dismiss-{key_prefix}-{row['id']}", icon=":material/cancel:"):
                _set_status(repository, [row["id"]], "dismissed", note); st.rerun()
        if row["rule_id"] in BASELINE_RULES and c.button("Aprobar como normal" if lang != "en" else "Approve baseline", key=f"approve-{key_prefix}-{row['id']}",
                                                         icon=":material/verified:"):
            repository.approve_alert(row["id"], SystemClock().now_iso()); refresh_data(); st.rerun()


def _bulk_actions(repository, selected: list[dict]):
    with st.container(border=True):
        st.markdown(f"**{len(selected)} alertas seleccionadas**")
        note = st.text_input("Nota para todas", key="bulk-note")
        a, b, c = st.columns(3)
        ids = [row["id"] for row in selected]
        if a.button("Confirmar seleccionadas", key="bulk-confirm", icon=":material/check_circle:"):
            _set_status(repository, ids, "confirmed", note); st.rerun()
        all_dismissed = all(row["status"] == "dismissed" for row in selected)
        if all_dismissed:
            if b.button("Reactivar seleccionadas", key="bulk-reactivate", icon=":material/replay:"):
                _set_status(repository, ids, "new", note or "Reactivadas en lote"); st.rerun()
        else:
            if b.button("Descartar seleccionadas", key="bulk-dismiss", icon=":material/cancel:"):
                _set_status(repository, ids, "dismissed", note); st.rerun()
        approvable = [row["id"] for row in selected if row["rule_id"] in BASELINE_RULES]
        if approvable and c.button(f"Aprobar como normal ({len(approvable)})", key="bulk-approve",
                                   icon=":material/verified:", help="Solo las de reglas con baseline: "
                                   + ", ".join(sorted(BASELINE_RULES))):
            now = SystemClock().now_iso()
            for alert_id in approvable:
                try:
                    repository.approve_alert(alert_id, now)
                except (KeyError, ValueError):
                    continue  # already covered by an earlier approval in this batch
            refresh_data(); st.rerun()


def _render_alerts_table(repository, query, rows: list[dict], curr_status_names: dict, lang: str, requested: str | None, key_prefix: str = "alerts"):
    if len(rows) > MAX_ALERTS_SHOWN:
        st.caption(f"Showing {MAX_ALERTS_SHOWN} of {len(rows)} alerts; use filters to narrow down." if lang == "en" else f"Mostrando {MAX_ALERTS_SHOWN} de {len(rows)} alertas; use los filtros para acotar.")
    shown_rows = rows[:MAX_ALERTS_SHOWN]
    selected: list[dict] = []
    if shown_rows:
        col_sev = "Severity" if lang == "en" else "Severidad"
        col_rule = "Rule" if lang == "en" else "Regla"
        col_title = "Title" if lang == "en" else "Título"
        col_summary = "Summary" if lang == "en" else "Resumen"
        col_status = "Status" if lang == "en" else "Estado"
        col_date = "Date" if lang == "en" else "Fecha"
        frame = pd.DataFrame([{"#": row["id"], col_sev: _severity_name(row["severity"], lang=lang), col_rule: row["rule_id"],
                               col_title: row["title"], col_summary: _alert_summary(row["evidence"]),
                               col_status: curr_status_names.get(row["status"], row["status"]),
                               col_date: to_local_datetime(row["ts"])} for row in shown_rows])
        event = st.dataframe(frame, hide_index=True, width="stretch", key=f"{key_prefix}-table", on_select="rerun",
                             selection_mode="multi-row",
                             column_config={"#": st.column_config.NumberColumn(format="%d", width="small"),
                                            col_date: st.column_config.DatetimeColumn(format=COLUMN_FORMAT)})
        st.caption("Select an alert to inspect details, or multiple to act on them together." if lang == "en" else "Seleccione una alerta para ver su detalle, o varias para actuar sobre todas a la vez.")
        selected = [shown_rows[index] for index in (event.selection.rows if event else []) if index < len(shown_rows)]
    else:
        empty("No alerts match the filters." if lang == "en" else "Ninguna alerta coincide con los filtros.")
    if len(selected) > 1:
        _bulk_actions(repository, selected)
        return
    target = selected[0] if selected else None
    if target is None and requested and str(requested).isdigit():
        target = query.alert(int(requested))
    if target is None and shown_rows and key_prefix == "alerts":
        target = shown_rows[0]
    if target:
        _alert_detail(repository, query, target, key_prefix=key_prefix)


def _alert_matches(row: dict, term: str) -> bool:
    """Case-insensitive search over useful alert fields, including structured evidence."""
    values = (row.get("rule_id"), row.get("severity"), row.get("title"), row.get("entity"),
              row.get("status"), row.get("status_note"), row.get("evidence"))
    return term.casefold() in " ".join(str(value or "") for value in values).casefold()


def alerts():
    _, repository, query, since = context()
    lang = st.session_state.get("language") or "es"
    hero("🚨 Alertas", "Lo que detectaron las reglas, con su evidencia y la explicación del LLM.", page_key="alerts", lang=lang)
    _bulk_learn(repository)
    rows = query.rows("alerts", since)
    _truncation_note(rows)
    requested = st.query_params.get("id")
    if not rows and not requested:
        empty_msg = f"No alerts. Click Analyze to evaluate rules R01–R{len(ALL_RULES):02d}." if lang == "en" else f"No hay alertas. Pulse Analizar para aplicar las reglas R01–R{len(ALL_RULES):02d}."
        return empty(empty_msg)

    search_col, path_col = st.columns(2)
    alert_search = search_col.text_input("Search alerts" if lang == "en" else "Buscar en alertas",
                                         placeholder="Rule, title, entity, evidence, note…" if lang == "en" else
                                                     "Regla, título, entidad, evidencia, nota…",
                                         icon=":material/search:", key="alert-search").casefold().strip()
    path_search = path_col.text_input("Path" if lang == "en" else "Ruta",
                                      placeholder=r"C:\Users\... or executable.exe" if lang == "en" else
                                                  r"C:\Usuarios\... o ejecutable.exe",
                                      icon=":material/search:", key="alert-path-search").strip()
    if alert_search:
        rows = [row for row in rows if _alert_matches(row, alert_search)]
    if path_search:
        try:
            path_alert_ids = set(query.alert_ids_by_path(path_search, since))
            rows = [row for row in rows if row["id"] in path_alert_ids]
        except ValueError as exc:
            st.warning(str(exc))
            rows = []
    if alert_search or path_search:
        st.caption(f"{len(rows)} matching alerts." if lang == "en" else
                   f"{len(rows)} alertas coinciden con la búsqueda.")

    open_rows = [row for row in rows if row["status"] in OPEN_STATUSES]
    dismissed_rows = [row for row in rows if row["status"] == "dismissed"]
    curr_status_names = status_names(lang=lang)

    tab_active_lbl = f":material/notification_important: {t('alerts.tabs.active', lang=lang, default='Alertas activas')} ({len(open_rows)})"
    tab_dism_lbl = f":material/archive: {t('alerts.tabs.dismissed', lang=lang, default='Descartadas (Historial)')} ({len(dismissed_rows)})"
    tab_time_lbl = f":material/timeline: {t('alerts.tabs.timelapse', lang=lang, default='Timelapse')}"

    tab_act, tab_dism, tab_time = st.tabs([tab_active_lbl, tab_dism_lbl, tab_time_lbl])

    with tab_act:
        labels_es = {"critical": "Críticas abiertas", "high": "Altas abiertas", "medium": "Medias abiertas", "low": "Bajas abiertas"}
        labels_en = {"critical": "Open critical", "high": "Open high", "medium": "Open medium", "low": "Open low"}
        labels = labels_en if lang == "en" else labels_es
        for column, (level, label) in zip(st.columns(4), labels.items()):
            column.metric(label, sum(row["severity"] == level for row in open_rows))

        if not open_rows and not requested:
            empty(t("alerts.no_active", lang=lang, default="No hay alertas activas en esta ventana temporal."))
        else:
            col_sev, col_rule = st.columns(2)
            severities = col_sev.multiselect("Severity" if lang == "en" else "Severidad", ["critical", "high", "medium", "low"],
                                             format_func=lambda s: _severity_name(s, lang=lang), key="act-alert-severity",
                                             placeholder="All" if lang == "en" else "Todas")
            rules = col_rule.multiselect("Rule" if lang == "en" else "Regla", sorted({row["rule_id"] for row in open_rows}),
                                         key="act-alert-rule", placeholder="All" if lang == "en" else "Todas",
                                         format_func=lambda rule: (f"{rule} · {rule_help(rule, lang=lang).detects[:45]}…" if rule_help(rule, lang=lang) else rule))
            filtered_open = [row for row in open_rows if (not severities or row["severity"] in severities) and (not rules or row["rule_id"] in rules)]
            rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            filtered_open.sort(key=lambda row: (rank.get(row["severity"], 4), row["ts"]))

            # Quick bulk dismiss for filtered alerts
            if filtered_open:
                dismiss_btn_label = t("alerts.bulk_dismiss_btn", lang=lang, count=len(filtered_open), default=f"Descartar las {len(filtered_open)} alertas filtradas")
                with st.expander(f":material/delete_sweep: {dismiss_btn_label}", expanded=False):
                    note_input = st.text_input(t("alerts.reason_label", lang=lang, default="Motivo del descarte"),
                                               value=t("alerts.reason_default", lang=lang, default="Descarte masivo de falsos positivos"),
                                               key="bulk-dismiss-filter-note")
                    if st.button(t("alerts.bulk_dismiss_confirm", lang=lang, count=len(filtered_open), default=f"Confirmar descarte de {len(filtered_open)} alertas"),
                                 key="confirm-bulk-filtered-btn", icon=":material/delete_sweep:", type="primary"):
                        _set_status(repository, [r["id"] for r in filtered_open], "dismissed", note_input)
                        st.rerun()

            col_mode, _ = st.columns([2, 3])
            mode = col_mode.radio(t("alerts.mode_label", lang=lang, default="Modo de visualización"),
                                  [t("alerts.mode_list", lang=lang, default="Lista de alertas"),
                                   t("alerts.mode_by_rule", lang=lang, default="Agrupadas por Regla"),
                                   t("alerts.mode_by_path", lang=lang, default="Agrupadas por ruta")],
                                  horizontal=True, label_visibility="collapsed", key="active-view-mode")

            if mode == t("alerts.mode_by_rule", lang=lang, default="Agrupadas por Regla"):
                from collections import defaultdict
                rule_groups = defaultdict(list)
                for r in filtered_open:
                    rule_groups[r["rule_id"]].append(r)

                rule_rows = []
                for r_id, g_alerts in sorted(rule_groups.items(), key=lambda item: len(item[1]), reverse=True):
                    r_info = rule_help(r_id, lang=lang)
                    r_detects = r_info.detects if r_info else r_id
                    sevs = sorted({a["severity"] for a in g_alerts}, key=lambda s: rank.get(s, 4))
                    highest_sev = _severity_name(sevs[0], lang=lang) if sevs else ""
                    rule_rows.append({
                        "Rule" if lang == "en" else "Regla": r_id,
                        "Severity" if lang == "en" else "Severidad": highest_sev,
                        "Detects" if lang == "en" else "Qué detecta": r_detects[:60] + "…" if len(r_detects) > 60 else r_detects,
                        "Count" if lang == "en" else "Alertas (#)": len(g_alerts),
                        "Date" if lang == "en" else "Fecha": to_local_datetime(max(a["ts"] for a in g_alerts)),
                    })

                df_rules = pd.DataFrame(rule_rows)
                event_rules = st.dataframe(df_rules, hide_index=True, width="stretch", key="alerts-rule-grouped",
                                           selection_mode="single-row", on_select="rerun",
                                           column_config={"Count" if lang == "en" else "Alertas (#)": st.column_config.NumberColumn(format="%d"),
                                                          "Date" if lang == "en" else "Fecha": st.column_config.DatetimeColumn(format=COLUMN_FORMAT)})
                sel_rule_idx = list(getattr(getattr(event_rules, "selection", None), "rows", None) or [])
                if sel_rule_idx and sel_rule_idx[0] < len(rule_rows):
                    chosen_rule_id = rule_rows[sel_rule_idx[0]]["Rule" if lang == "en" else "Regla"]
                    alerts_in_rule = rule_groups[chosen_rule_id]
                    with st.container(border=True):
                        st.markdown(f"**{chosen_rule_id}** · {len(alerts_in_rule)} " + ("alerts" if lang == "en" else "alertas"))
                        btn_dismiss_rule = t("alerts.dismiss_rule_btn", lang=lang, count=len(alerts_in_rule), rule=chosen_rule_id, default=f"Descartar las {len(alerts_in_rule)} de {chosen_rule_id}")
                        if st.button(btn_dismiss_rule, icon=":material/delete_sweep:", key=f"dismiss-rule-btn-{chosen_rule_id}"):
                            _set_status(repository, [a["id"] for a in alerts_in_rule], "dismissed", f"Descarte de regla {chosen_rule_id}")
                            st.rerun()
                        _render_alerts_table(repository, query, alerts_in_rule, curr_status_names, lang, requested, key_prefix=f"sub-act-{chosen_rule_id}")
                elif not sel_rule_idx and filtered_open:
                    st.caption("Seleccione una regla de la tabla para ver y gestionar sus alertas." if lang != "en" else "Select a rule from the table to view and manage its alerts.")
            elif mode == t("alerts.mode_by_path", lang=lang, default="Agrupadas por ruta"):
                from collections import defaultdict
                paths_by_alert = query.alert_paths([row["id"] for row in filtered_open])
                path_groups = defaultdict(list)
                without_path = []
                for alert in filtered_open:
                    paths = paths_by_alert.get(alert["id"], [])
                    if paths:
                        path_groups[paths[0]].append(alert)
                    else:
                        without_path.append(alert)

                path_rows = []
                for path, path_alerts in sorted(path_groups.items(), key=lambda item: (-len(item[1]), item[0].casefold())):
                    severities = sorted({alert["severity"] for alert in path_alerts}, key=lambda value: rank.get(value, 4))
                    path_rows.append({
                        "Path" if lang == "en" else "Ruta": path,
                        "Severity" if lang == "en" else "Severidad": _severity_name(severities[0], lang=lang),
                        "Count" if lang == "en" else "Alertas (#)": len(path_alerts),
                        "Date" if lang == "en" else "Fecha": to_local_datetime(max(alert["ts"] for alert in path_alerts)),
                    })

                if path_rows:
                    path_column = "Path" if lang == "en" else "Ruta"
                    count_column = "Count" if lang == "en" else "Alertas (#)"
                    date_column = "Date" if lang == "en" else "Fecha"
                    path_event = st.dataframe(
                        pd.DataFrame(path_rows), hide_index=True, width="stretch", key="alerts-path-grouped",
                        selection_mode="single-row", on_select="rerun",
                        column_config={count_column: st.column_config.NumberColumn(format="%d"),
                                       date_column: st.column_config.DatetimeColumn(format=COLUMN_FORMAT)},
                    )
                    selected_paths = list(getattr(getattr(path_event, "selection", None), "rows", None) or [])
                    if selected_paths and selected_paths[0] < len(path_rows):
                        selected_index = selected_paths[0]
                        selected_path = path_rows[selected_index][path_column]
                        alerts_in_path = path_groups[selected_path]
                        with st.container(border=True):
                            st.markdown(f"**{_plain(selected_path)}** · {len(alerts_in_path)} " +
                                        ("alerts" if lang == "en" else "alertas"))
                            _render_alerts_table(repository, query, alerts_in_path, curr_status_names, lang, requested,
                                                 key_prefix=f"sub-path-{selected_index}")
                    elif filtered_open:
                        st.caption("Select a path to view its alerts." if lang == "en" else
                                   "Seleccione una ruta para ver sus alertas.")
                else:
                    empty("No alerts contain an identifiable path." if lang == "en" else
                          "Ninguna alerta contiene una ruta identificable.")

                if without_path:
                    with st.expander((f"Without an identifiable path ({len(without_path)})" if lang == "en" else
                                      f"Sin ruta identificada ({len(without_path)})"), expanded=False):
                        _render_alerts_table(repository, query, without_path, curr_status_names, lang, requested,
                                             key_prefix="sub-path-none")
            else:
                _render_alerts_table(repository, query, filtered_open, curr_status_names, lang, requested, key_prefix="alerts")

    with tab_dism:
        if not dismissed_rows:
            empty(t("alerts.no_dismissed", lang=lang, default="No hay alertas descartadas en esta ventana temporal."))
        else:
            col_d_sev, col_d_rule = st.columns(2)
            d_severities = col_d_sev.multiselect("Severity" if lang == "en" else "Severidad", ["critical", "high", "medium", "low"],
                                                 format_func=lambda s: _severity_name(s, lang=lang), key="dism-severity",
                                                 placeholder="All" if lang == "en" else "Todas")
            d_rules = col_d_rule.multiselect("Rule" if lang == "en" else "Regla", sorted({r["rule_id"] for r in dismissed_rows}),
                                             key="dism-rule", placeholder="All" if lang == "en" else "Todas",
                                             format_func=lambda rule: (f"{rule} · {rule_help(rule, lang=lang).detects[:45]}…" if rule_help(rule, lang=lang) else rule))
            filtered_dism = [r for r in dismissed_rows if (not d_severities or r["severity"] in d_severities) and (not d_rules or r["rule_id"] in d_rules)]
            filtered_dism.sort(key=lambda r: (r.get("status_at") or r["ts"]), reverse=True)

            if not filtered_dism:
                empty(t("alerts.no_match_filters", lang=lang, default="Ninguna alerta coincide con los filtros."))
            else:
                col_sev = "Severity" if lang == "en" else "Severidad"
                col_rule = "Rule" if lang == "en" else "Regla"
                col_title = "Title" if lang == "en" else "Título"
                col_date = "Date" if lang == "en" else "Fecha evento"
                col_d_date = t("alerts.dismissed_at", lang=lang, default="Fecha de descarte")
                col_note = t("alerts.dismissed_note", lang=lang, default="Motivo / Nota")
                d_frame = pd.DataFrame([{
                    "#": r["id"],
                    col_sev: _severity_name(r["severity"], lang=lang),
                    col_rule: r["rule_id"],
                    col_title: r["title"],
                    col_date: to_local_datetime(r["ts"]),
                    col_d_date: to_local_datetime(r["status_at"]) if r.get("status_at") else None,
                    col_note: r.get("status_note") or "-"
                } for r in filtered_dism[:MAX_ALERTS_SHOWN]])
                d_event = st.dataframe(d_frame, hide_index=True, width="stretch", key="dism-table", on_select="rerun",
                                       selection_mode="single-row",
                                       column_config={"#": st.column_config.NumberColumn(format="%d", width="small"),
                                                      col_date: st.column_config.DatetimeColumn(format=COLUMN_FORMAT),
                                                      col_d_date: st.column_config.DatetimeColumn(format=COLUMN_FORMAT)})
                st.caption("Seleccione una alerta descartada para ver su detalle o reactivarla." if lang != "en" else "Select a dismissed alert to view details or reactivate it.")
                d_sel = list(getattr(getattr(d_event, "selection", None), "rows", None) or [])
                d_target = filtered_dism[d_sel[0]] if d_sel and d_sel[0] < len(filtered_dism) else None
                if d_target:
                    _alert_detail(repository, query, d_target, key_prefix="dism")

    with tab_time:
        st.subheader(":material/timeline: " + t("alerts.timelapse_title", lang=lang, default="Evolución cronológica de alertas"), divider="gray")
        if not rows:
            empty("No hay datos para construir la línea de tiempo." if lang != "en" else "No data to build timeline.")
        else:
            tl_data = []
            for r in rows:
                dt = to_local_datetime(r["ts"])
                hour_str = dt.strftime("%Y-%m-%d %H:00")
                st_code = r["status"]
                if st_code in OPEN_STATUSES:
                    st_label = "Activa" if lang != "en" else "Active"
                elif st_code == "dismissed":
                    st_label = "Descartada" if lang != "en" else "Dismissed"
                else:
                    st_label = "Confirmada" if lang != "en" else "Confirmed"
                tl_data.append({
                    "hour": hour_str,
                    "status": st_label,
                    "alert_id": r["id"],
                    "rule": r["rule_id"],
                })

            df_raw_tl = pd.DataFrame(tl_data)
            df_grouped = df_raw_tl.groupby(["hour", "status"]).size().reset_index(name="count")
            df_grouped.sort_values(by="hour", inplace=True)

            color_map = {
                "Activa": "#EF4444", "Active": "#EF4444",
                "Descartada": "#64748B", "Dismissed": "#64748B",
                "Confirmada": "#3B82F6", "Confirmed": "#3B82F6",
            }
            fig_tl = px.bar(
                df_grouped,
                x="hour",
                y="count",
                color="status",
                color_discrete_map=color_map,
                barmode="stack",
                labels={"hour": "Hora" if lang != "en" else "Hour",
                        "count": "Alertas" if lang != "en" else "Alerts",
                        "status": "Estado" if lang != "en" else "Status"},
            )
            fig_tl.update_layout(xaxis_title="", yaxis_title="Alertas" if lang != "en" else "Alerts", hovermode="x unified",
                                 legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            chart(fig_tl, key="alerts-timelapse-chart")
            st.caption(t("alerts.timelapse_caption", lang=lang,
                         default="Compara la aparición de alertas activas frente a las que fueron descartadas o confirmadas en el tiempo."))

            unique_hours = sorted(df_raw_tl["hour"].unique(), reverse=True)
            if unique_hours:
                st.divider()
                st.markdown("**" + ("Explore alerts by hour:" if lang == "en" else "Explorar alertas por bloque horario:") + "**")
                chosen_hour = st.selectbox("Bloque horario", unique_hours, key="tl-hour-pick", label_visibility="collapsed")
                hour_alerts = [r for r in rows if to_local_datetime(r["ts"]).strftime("%Y-%m-%d %H:00") == chosen_hour]
                st.caption(f"{len(hour_alerts)} " + ("alerts recorded in this hour:" if lang == "en" else "alertas registradas en esta hora:"))
                col_s = "Severity" if lang == "en" else "Severidad"
                col_r = "Rule" if lang == "en" else "Regla"
                col_t = "Title" if lang == "en" else "Título"
                col_st = "Status" if lang == "en" else "Estado"
                col_d = "Date" if lang == "en" else "Fecha"
                f_hour = pd.DataFrame([{"#": r["id"], col_s: _severity_name(r["severity"], lang=lang),
                                       col_r: r["rule_id"], col_t: r["title"],
                                       col_st: curr_status_names.get(r["status"], r["status"]),
                                       col_d: to_local_datetime(r["ts"])} for r in hour_alerts])
                st.dataframe(f_hour, hide_index=True, width="stretch", key="tl-hour-table",
                             column_config={"#": st.column_config.NumberColumn(format="%d", width="small"),
                                            col_d: st.column_config.DatetimeColumn(format=COLUMN_FORMAT)})



# --- Evidencia -------------------------------------------------------------------------------------

def _hourly_chart(query, table_name: str, since: str, by: str | None, names: dict | None = None, key: str = ""):
    points = query.hourly(table_name, since, by)
    if not points:
        return
    frame = hourly_frame(points, since, time_key="hora", value_key="total", series_key="serie" if by else None)
    if by:
        frame["serie"] = frame["serie"].map(lambda value: (names or {}).get(int(value) if value.isdigit() else value, value))
    figure = px.bar(frame, x="hora", y="total", color="serie" if by else None, labels={"hora": "", "total": "eventos", "serie": ""})
    figure.update_traces(hovertemplate="%{x|%d/%m %H:%M} · %{y} eventos<extra>%{fullData.name}</extra>")
    chart(_time_axis(_style(figure, 300), hourly_bars=True), key=f"hourly-{key}")


def _top_chart(query, table_name: str, column: str, since: str, title: str, names: dict | None = None, key: str = ""):
    items = query.grouped(table_name, column, since)
    st.markdown(f"**{title}**")
    if not items:
        return st.caption("Sin datos.")
    frame = pd.DataFrame(items)
    frame["valor"] = frame["valor"].map(lambda value: network.safe((names or {}).get(value, value), 40))
    figure = px.bar(frame.iloc[::-1], x="total", y="valor", orientation="h", text="total", labels={"valor": "", "total": ""})
    figure.update_traces(textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{x}<extra></extra>")
    figure.update_xaxes(showticklabels=False, showgrid=False)
    chart(_style(figure, 300), key=f"top-{key}")


def access():
    settings, _, query, since = context()
    lang = st.session_state.get("language") or "es"
    hero("🔑 Accesos", "Inicios de sesión, intentos fallidos, RDP y cambios de cuentas.", page_key="access", lang=lang)
    _section_summary(query, settings, "accesos")
    rows = query.rows("auth_events", since)
    _truncation_note(rows)
    if not rows:
        empty("No access events. The Security log requires Administrator or the «Event Log Readers» group (start\\configurar-permisos.bat)."
              if lang == "en" else
              "Sin eventos de acceso. El registro Security necesita administrador o el grupo «Lectores del registro de eventos» (start\\configurar-permisos.bat).")
        return
    a, b, c, d = st.columns(4)
    a.metric("Successful logons" if lang == "en" else "Inicios correctos", sum(row["event_id"] == 4624 for row in rows))
    b.metric("Failed attempts" if lang == "en" else "Intentos fallidos", sum(row["event_id"] == 4625 for row in rows))
    c.metric("RDP", sum(row["event_id"] == 1149 or (row["event_id"] == 4624 and row.get("logon_type") == 10) for row in rows))
    d.metric("Account changes" if lang == "en" else "Cambios de cuentas", sum(row["event_id"] in (4720, 4732) for row in rows))
    _hourly_chart(query, "auth_events", since, "event_id", EVENT_NAMES, key="auth")
    left, right = st.columns(2)
    with left: _top_chart(query, "auth_events", "source_ip", since, "Most frequent sources" if lang == "en" else "Orígenes más frecuentes", key="auth-ip")
    with right: _top_chart(query, "auth_events", "target_user", since, "Most used accounts" if lang == "en" else "Cuentas más usadas", key="auth-user")
    with st.expander("Details" if lang == "en" else "Detalle", icon=":material/table:"):
        table(rows, key="auth_events", view="auth_events", lang=lang)


def files():
    settings, _, query, since = context()
    lang = st.session_state.get("language") or "es"
    hero("📁 Archivos", "Creaciones, cambios, renombrados y borrados en las carpetas vigiladas.", page_key="files", lang=lang)
    _section_summary(query, settings, "archivos")
    rows = query.rows("file_events", since)
    _truncation_note(rows)
    if not rows:
        empty("No file events. Click Collect or run start\\vigilar.bat." if lang == "en" else "Sin eventos de archivos. Pulse Recolectar o ejecute start\\vigilar.bat.")
    else:
        a, b, c, d = st.columns(4)
        a.metric("Created / new" if lang == "en" else "Creados / nuevos", sum(row["action"] in ("created", "observed_new") for row in rows))
        b.metric("Modified" if lang == "en" else "Modificados", sum(row["action"] in ("modified", "observed_changed") for row in rows))
        c.metric("Renamed" if lang == "en" else "Renombrados", sum(row["action"] == "moved" for row in rows))
        d.metric("Deleted" if lang == "en" else "Borrados", sum(row["action"] == "deleted" for row in rows))
        _hourly_chart(query, "file_events", since, "action", key="files")
        left, right = st.columns(2)
        with left: _top_chart(query, "file_events", "extension", since, "Extensions" if lang == "en" else "Extensiones", key="files-ext")
        with right: _top_chart(query, "file_events", "action", since, "Actions" if lang == "en" else "Acciones", key="files-action")
        with st.expander("Details" if lang == "en" else "Detalle", icon=":material/table:"):
            table(rows, key="file_events", view="file_events", lang=lang,
                  on_pick=lambda record: path_actions(record, "file-event", lang))
    _duplicate_files(query, since, lang)
    _reputation_panel(settings, query, lang)


def _duplicate_files(query, since: str, lang: str):
    st.subheader("Repeated files" if lang == "en" else "Archivos repetidos", divider="gray")
    st.caption("Same SHA-256 at different observed paths. Repeated events for one path count only once."
               if lang == "en" else
               "Mismo SHA-256 en rutas observadas distintas. Los eventos repetidos de una sola ruta cuentan una vez.")
    rows = query.duplicate_files(since)
    if not rows:
        st.info("No repeated files with a calculated hash were found in this time window."
                if lang == "en" else
                "No se encontraron archivos repetidos con hash calculado en esta ventana.")
        return
    groups = {}
    for row in rows:
        groups.setdefault(row["sha256"], []).append(row)
    extra_copies = sum(max(len(items) - 1, 0) for items in groups.values())
    recoverable = sum(max(len(items) - 1, 0) * max(int(item.get("size") or 0) for item in items)
                      for items in groups.values())
    a, b, c = st.columns(3)
    a.metric("Duplicate groups" if lang == "en" else "Grupos duplicados", len(groups))
    b.metric("Additional copies" if lang == "en" else "Copias adicionales", extra_copies)
    c.metric("Potential duplicate size" if lang == "en" else "Tamaño duplicado potencial",
             f"{recoverable / 1024 ** 2:.1f} MB")
    shown = [{"SHA-256": row["sha256"], "ruta": row["path"],
              "tamaño": row.get("size"), "última observación": row["ts"],
              "copias": len(groups[row["sha256"]])} for row in rows]
    table(shown, key="duplicate-files", windowed=True, lang=lang,
          dates=("última observación",),
          columns={"tamaño": st.column_config.NumberColumn(format="%d bytes"),
                   "copias": st.column_config.NumberColumn(format="%d")},
          on_pick=lambda record: path_actions(record, "duplicate-file", lang))
    st.caption("La cifra es orientativa: Atalaya no elimina archivos y una ruta observada podría haber cambiado "
               "desde la recolección." if lang != "en" else
               "The estimate is informational: Atalaya never deletes files, and an observed path may have changed.")


def _reputation_panel(settings, query, lang):
    from dataclasses import asdict, replace
    from bootstrap import build_reputation_service

    st.subheader("Executable reputation" if lang == "en" else "Reputación de ejecutables")
    st.caption("Inspect a local executable without running it. Local analysis calculates SHA-256 and verifies its "
               "Authenticode signature."
               if lang == "en" else
               "Inspecciona un ejecutable local sin abrirlo: calcula SHA-256 y comprueba su firma Authenticode.")
    with st.form("reputation-inspect"):
        path = st.text_input("File path" if lang == "en" else "Ruta del archivo",
                             placeholder=r"C:\ruta\programa.exe", key="reputation-path")
        online = st.checkbox("Check SHA-256 with VirusTotal" if lang == "en" else
                             "Consultar el SHA-256 en VirusTotal", value=False, key="reputation-online",
                             help="Only the SHA-256 is sent; the file and its path remain on this computer."
                             if lang == "en" else
                             "Sólo se envía el SHA-256; el archivo y su ruta permanecen en este equipo.")
        api_key = st.text_input("VirusTotal API key (used only for this check)" if lang == "en" else
                                "Clave API de VirusTotal (sólo para esta consulta)", type="password",
                                disabled=not online or bool(settings.virustotal_api_key), key="reputation-api-key",
                                help="Atalaya already has a configured key." if lang == "en" and settings.virustotal_api_key
                                else "Atalaya ya tiene una clave configurada." if settings.virustotal_api_key else None)
        submitted = st.form_submit_button("Inspect file" if lang == "en" else "Analizar archivo",
                                          icon=":material/shield:")
    if submitted:
        if not path.strip():
            st.error("Enter the path of an executable." if lang == "en" else
                     "Introduzca la ruta de un ejecutable.")
        elif online and not (settings.virustotal_api_key or api_key.strip()):
            st.error("Enter a VirusTotal API key to perform the online check."
                     if lang == "en" else "Introduzca una clave API de VirusTotal para realizar la consulta online.")
        else:
            effective = replace(settings, virustotal_api_key=settings.virustotal_api_key or api_key.strip() or None)
            try:
                with st.spinner("Inspecting without executing the file…" if lang == "en" else
                                "Analizando sin ejecutar el archivo…"):
                    result = build_reputation_service(effective).inspect(Path(path.strip()), online=online)
                st.session_state["reputation-result"] = asdict(result)
                refresh_data()
            except (OSError, RuntimeError, ValueError) as exc:
                st.error(("The file could not be inspected: " if lang == "en" else
                          "No se pudo analizar el archivo: ") + f"{type(exc).__name__}: {exc}")
    result = st.session_state.get("reputation-result")
    if result:
        signature = result.get("local", {}).get("signature", {})
        a, b, c = st.columns(3)
        a.metric("Verdict" if lang == "en" else "Veredicto", result["verdict"])
        b.metric("Confidence" if lang == "en" else "Confianza", f"{result['confidence']:.0%}")
        c.metric("Authenticode", signature.get("status") or ("Not checked" if lang == "en" else "No comprobada"))
        st.code(result["sha256"], language=None)
        for reason in result.get("reasons", []):
            st.write(f"- {reason}")
        if result.get("external"):
            st.json(result["external"], expanded=False)
    st.caption("The executable is never uploaded. Online enrichment is optional and sends only its SHA-256."
               if lang == "en" else
               "El ejecutable nunca se carga. La consulta online es opcional y envía únicamente su SHA-256.")
    reputations = query.rows("file_reputation", None, 100)
    table(reputations, key="file_reputation", view="file_reputation", windowed=False, lang=lang,
          on_pick=lambda record: path_actions(record, "reputation", lang))


def persistence():
    settings, _, query, since = context()
    lang = st.session_state.get("language") or "es"
    hero("🔄 Persistencia", "Lo que arranca solo: claves Run, carpeta Inicio, tareas programadas y servicios.", page_key="persistence", lang=lang)
    _section_summary(query, settings, "persistencia")
    rows = query.rows("persistence_items", since)
    _truncation_note(rows)
    if not rows:
        return empty("Nothing new in this window. Click Collect to inventory Run keys, Startup folder, tasks, and services."
                     if lang == "en" else
                     "Nada nuevo en la ventana. Pulse Recolectar para inventariar Run, Inicio, tareas y servicios.")
    names_es = {"run_key": "Claves Run", "startup_folder": "Carpeta Inicio", "scheduled_task": "Tareas", "service": "Servicios"}
    names_en = {"run_key": "Run Keys", "startup_folder": "Startup Folder", "scheduled_task": "Tasks", "service": "Services"}
    names = names_en if lang == "en" else names_es
    new_sfx = " (new)" if lang == "en" else " (nuevos)"
    for column, (kind, label) in zip(st.columns(4), names.items()):
        column.metric(f"{label}{new_sfx}", sum(row["kind"] == kind for row in rows))
    top_title = "Items first seen, by type" if lang == "en" else "Elementos vistos por primera vez, por tipo"
    _top_chart(query, "persistence_items", "kind", since, top_title, names, key="persistence")
    with st.expander("Details" if lang == "en" else "Detalle", icon=":material/table:"):
        table(rows, key="persistence_items", view="persistence_items", lang=lang,
              on_pick=lambda record: path_actions(record, "persistence", lang))


def firewall():
    settings, _, query, since = context()
    lang = st.session_state.get("language") or "es"
    hero("🧱 Firewall", "Paquetes que el firewall de Windows bloqueó: quién intentó entrar y a qué puertos.", page_key="firewall", lang=lang)
    _section_summary(query, settings, "firewall")
    rows = query.rows("firewall_events", since)
    _truncation_note(rows)
    if not rows:
        empty("No firewall events. Enable dropped packet logging with start\\configurar-permisos.bat."
              if lang == "en" else
              "Sin eventos del firewall. Active el registro de paquetes bloqueados con start\\configurar-permisos.bat.")
        return
    a, b, c = st.columns(3)
    a.metric("Blocked" if lang == "en" else "Bloqueados", sum(row.get("action") == "DROP" for row in rows))
    b.metric("Distinct sources" if lang == "en" else "Orígenes distintos", len({row.get("src_ip") for row in rows}))
    c.metric("Targeted ports" if lang == "en" else "Puertos atacados", len({row.get("dst_port") for row in rows}))
    _hourly_chart(query, "firewall_events", since, "action", key="firewall")

    left, right = st.columns(2)
    with left: _top_chart(query, "firewall_events", "src_ip", since, "Orígenes más insistentes", key="fw-src")
    with right: _top_chart(query, "firewall_events", "dst_port", since, "Puertos más buscados",
                           {port: f"{port} · {name}" for port, name in network.SERVICES.items()}, key="fw-port")
    with st.expander("Detalle", icon=":material/table:"):
        table(rows, key="firewall_events", view="firewall_events")


# --- Herramientas ----------------------------------------------------------------------------------

AI_SIZES = {"compacto": "Compacto · 25 alertas", "completo": "Completo · 100 alertas"}


def _ai_export_panel(settings):
    """A Markdown dossier for a more capable AI. Atalaya does not send it anywhere: the person downloads it."""
    from bootstrap import build_ai_report_service

    st.subheader(":material/smart_toy: Expediente para una IA externa", divider="gray")
    st.caption("Un Markdown con instrucciones, contexto, alertas, conclusiones del LLM local y datos de cada sección, "
               "listo para pegar en una IA más capaz y pedirle un análisis completo.")
    a, b, c = st.columns([2, 3, 3], vertical_alignment="bottom")
    hours = selected_window_hours()
    a.metric("Ventana", st.session_state.get("window", "24 horas"), help="La de la barra lateral.")
    size = b.segmented_control("Tamaño", list(AI_SIZES), default="compacto", format_func=AI_SIZES.get,
                               key="ai-size") or "compacto"
    pseudonymize = c.toggle("Seudonimizar", value=True, key="ai-pseudo",
                            help="Cambia cuentas, nombre del equipo, correos e IP privadas por USUARIO_1, EQUIPO_1, "
                                 "CORREO_1, IP_LOCAL_1… El mapa queda solo en este equipo.")
    public_ips = c.toggle("Ocultar también IP públicas", value=False, key="ai-public", disabled=not pseudonymize,
                          help="Las IP públicas ayudan a la IA a reconocer servicios conocidos; ocúltelas si prefiere "
                               "no revelar con quién se comunica el equipo.")
    if st.button("Preparar expediente", icon=":material/assignment:", key="ai-build"):
        with st.spinner("Reuniendo la evidencia…"):
            st.session_state["ai-export"] = build_ai_report_service(settings).build(
                hours, size, pseudonymize, public_ips)
    report = st.session_state.get("ai-export")
    if not report:
        return
    m1, m2, m3 = st.columns(3)
    m1.metric("Caracteres", f"{report['chars']:,}")
    m2.metric("Tokens aproximados", f"{report['tokens']:,}", help="Estimación: 4 caracteres por token.")
    m3.metric("Alertas en la ventana", f"{report['alerts']:,}")
    if report["mapping"]:
        st.warning("Al pegarlo en un servicio en la nube, este contenido sale del equipo. Está seudonimizado, pero "
                   "contiene rutas, procesos e IP públicas: revíselo antes de compartirlo.", icon=":material/shield:")
    else:
        st.error("Este expediente NO está seudonimizado: incluye nombres de cuentas, del equipo e IP privadas.",
                 icon=":material/warning:")
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    st.download_button("Descargar expediente (.md)", report["markdown"].encode("utf-8"),
                       f"atalaya_expediente_ia_{stamp}.md", "text/markdown", icon=":material/download:",
                       type="primary", key="ai-download")
    with st.expander("Vista previa y copiar", icon=":material/content_copy:"):
        st.caption("Use el icono de copiar de la esquina para llevar todo el texto al portapapeles.")
        st.code(report["markdown"], language="markdown")  # shown as text: never rendered
    if report["mapping"]:
        with st.expander("Mapa de seudónimos (solo en este equipo, no va en el archivo)", icon=":material/key:"):
            st.dataframe(pd.DataFrame([{"Seudónimo": alias, "Valor real": real}
                                       for alias, real in report["mapping"].items()]),
                         hide_index=True, width="stretch", key="ai-mapping")


def reports():
    settings, _, _, _ = context()
    lang = st.session_state.get("language") or "es"
    hero("📄 Informes", "Informes Markdown del comando report y expedientes para analizar con una IA externa.", page_key="reports", lang=lang)
    _ai_export_panel(settings)
    st.subheader(":material/description: " + ("Generated Reports" if lang == "en" else "Informes generados"), divider="gray")
    st.caption("Creates a report from the evidence and analyses already stored in Atalaya."
               if lang == "en" else
               "Crea un informe con la evidencia y los análisis que Atalaya ya tiene guardados.")
    if st.button("Generate report" if lang == "en" else "Generar informe",
                 icon=":material/note_add:", type="primary", key="generate-report"):
        from bootstrap import build_report_service
        try:
            with st.spinner("Generating report…" if lang == "en" else "Generando informe…"):
                created = build_report_service(settings).execute()
            st.success(("Report created: " if lang == "en" else "Informe creado: ") + created.name)
        except (OSError, RuntimeError, ValueError) as exc:
            st.error(("The report could not be created: " if lang == "en" else "No se pudo crear el informe: ")
                     + f"{type(exc).__name__}: {exc}")
    paths = sorted(settings.reports_dir.glob("*.md"), reverse=True) if settings.reports_dir.exists() else []
    if not paths:
        return empty("There are no reports yet. Select Generate report."
                     if lang == "en" else "Todavía no hay informes. Pulse «Generar informe».")
    chosen = st.selectbox("Report" if lang == "en" else "Informe", paths, format_func=lambda p: p.name)
    content = chosen.read_text(encoding="utf-8")
    # The report embeds LLM text: rendering it as Markdown would let an injected ![](http://...) leak data off the machine
    st.code(content, language="markdown")
    st.download_button("Download" if lang == "en" else "Descargar", content.encode("utf-8"), chosen.name, "text/markdown", icon=":material/download:")



_plain = plain_label


def _rag_panel():
    from bootstrap import build_rag_service
    rag_status = build_rag_service(lexical_only=True).status()
    with st.expander(f"Índice RAG local · {rag_status['chunks']} chunks, {rag_status['embedded']} con embeddings",
                     icon=":material/library_books:"):
        use_embeddings = st.checkbox("Generar embeddings con Ollama", value=True)
        if st.button("Indexar documentación confiable"):
            with st.status("Indexando documentación local...") as index_status:
                try:
                    result = build_rag_service(lexical_only=not use_embeddings).index()
                except (ValueError, OSError) as exc:
                    index_status.update(label="No se pudo indexar", state="error")
                    st.error(str(exc))
                else:
                    index_status.update(label=f"Indexados {result['chunks']} chunks", state="complete")
                    if result["embedding_error"]: st.warning(result["embedding_error"])
                    if result["removed_sources"]: st.caption("Retiradas del índice: " + ", ".join(result["removed_sources"]))


def _show_message(message: dict):
    role = {"user": "user", "assistant": "assistant", "error": "assistant"}[message["role"]]
    with st.chat_message(role):
        if message["role"] == "error":
            st.error("Chat local no disponible")
        if message["role"] == "assistant":
            # The model writes Markdown; images, links and URLs are neutralized (see safe_markdown)
            st.markdown(safe_markdown(message["content"], st.session_state.get("language") or "es"))
        else:
            st.text(message["content"])
        details = [_local(message["ts"])]
        if message.get("model"): details.append(message["model"])
        if message.get("duration_ms"): details.append(f"{message['duration_ms'] / 1000:.1f} s")
        st.caption(" · ".join(details))
        if message.get("tool_calls"):
            with st.expander("Herramientas y evidencia consultadas"):
                st.json(message["tool_calls"])


def _chat_suggestions(query, lang: str) -> list[str]:
    """Starter questions; the first ones follow what is in the data right now."""
    tr = lambda es, en: en if lang == "en" else es
    severities = query.open_alerts_by_severity()
    serious = severities.get("critical", 0) + severities.get("high", 0)
    suggestions = []
    if serious:
        suggestions.append(tr(f"Hay {serious} alertas críticas o altas abiertas: ¿cuál reviso primero y por qué?",
                              f"There are {serious} open critical or high alerts: which should I review first and why?"))
    elif sum(severities.values()):
        suggestions.append(tr("¿Qué alertas abiertas hay y cuáles podrían ser falsos positivos?",
                              "Which alerts are open and which could be false positives?"))
    else:
        suggestions.append(tr("¿Hubo alguna alerta en las últimas 24 horas?", "Were there any alerts in the last 24 hours?"))
    suggestions += [
        tr("¿Con qué servicios de Internet se conectó este equipo hoy?",
           "Which Internet services did this computer connect to today?"),
        tr("¿Hubo inicios de sesión fallidos o accesos remotos esta semana?",
           "Were there failed logons or remote access this week?"),
        tr("¿Qué programas nuevos se configuraron para arrancar con Windows?",
           "Which new programs were set to start with Windows?"),
        tr("¿Qué procesos usan más memoria ahora y alguno parece sospechoso?",
           "Which processes use the most memory now, and does any look suspicious?"),
        tr("¿Qué puertos tiene abiertos este equipo y quién se conecta a ellos?",
           "Which ports does this computer have open and who connects to them?"),
        tr("¿Cómo activo el registro del firewall de Windows?", "How do I turn on the Windows firewall log?"),
        tr("¿Hay ejecutables con mala reputación o sin firma válida?",
           "Are there executables with bad reputation or no valid signature?"),
    ]
    return suggestions[:8]


def _suggestion_buttons(suggestions: list[str], key: str, columns: int = 2):
    """Clicking a suggestion sends it as the next question."""
    grid = st.columns(columns)
    for index, text in enumerate(suggestions):
        if grid[index % columns].button(text, key=f"{key}-{index}", width="stretch", icon=":material/lightbulb:",
                                        help=text):  # long questions are truncated on the button
            st.session_state["chat-pending"] = text
            st.rerun()


def chat():
    _, _, query, _ = context(window_applies=False)
    lang = st.session_state.get("language") or "es"
    hero("💬 Chat", "Pregunte en lenguaje natural sobre la evidencia recolectada y la documentación local. "
                    "Las conversaciones se guardan en la base local para consultarlas después.", page_key="chat", lang=lang)
    from bootstrap import build_chat_history
    history = build_chat_history()
    status = ai_status()
    if status["chat_tools"] is False:
        warn_msg = (f"{status['roles'].get('chat')} does not support tools: chat cannot inspect evidence. Choose another model in Local AI."
                    if lang == "en" else
                    f"{status['roles'].get('chat')} no admite herramientas: el chat no podrá consultar la evidencia. Elija otro modelo de chat en IA local.")
        st.warning(warn_msg, icon=":material/build:")
        _link(AI_PAGE, "Open Local AI" if lang == "en" else "Abrir IA local", ":material/tune:")

    sessions_col, conversation_col = st.columns([1, 3], gap="large")
    with sessions_col:
        st.markdown("**Conversations**" if lang == "en" else "**Conversaciones**")
        if st.button("New conversation" if lang == "en" else "Nueva conversación", icon=":material/add_comment:", width="stretch", key="chat-new"):
            st.session_state["chat_session_id"] = None
        search = st.text_input("Buscar" if lang != "en" else "Search",
                               placeholder="text in questions or answers" if lang == "en" else "texto en preguntas o respuestas",
                               key="chat-search", label_visibility="collapsed")
        if st.session_state.pop("chat-show-active", False):  # a restore asked for the active list; set before drawing
            st.session_state["chat-archived"] = False
        show_archived = st.toggle("Archived" if lang == "en" else "Archivadas", key="chat-archived",
                                  help=("Conversations you archived: hidden from the list, nothing is deleted."
                                        if lang == "en" else
                                        "Conversaciones que archivó: ocultas de la lista, no se borra nada."))
        sessions = history.list_sessions(search or None, 50, archived=show_archived)
        if not sessions:
            if lang == "en":
                st.caption("No archived conversations." if show_archived else
                           "No conversations" + (" match." if search else " yet."))
            else:
                st.caption("No hay conversaciones archivadas." if show_archived else
                           "Sin conversaciones" + (" que coincidan." if search else " todavía."))
        current = st.session_state.get("chat_session_id")
        for session in sessions:
            msg_word = "msg" if lang == "en" else "msj"
            label = f"{_plain(session['title'])}  \n{_local(session['updated_at'])} · {session['messages']} {msg_word}"
            if st.button(label, key=f"chat-session-{session['id']}", width="stretch",
                         type="primary" if session["id"] == current else "secondary"):
                st.session_state["chat_session_id"] = session["id"]
                st.rerun()

    with conversation_col:
        _rag_panel()
        current = st.session_state.get("chat_session_id")
        session = history.get_session(current) if current else None
        if current and session is None:  # deleted elsewhere
            st.session_state["chat_session_id"] = current = None
        if session:
            top_left, top_right = st.columns([3, 1])
            created_word = "created" if lang == "en" else "creada"
            archived_word = (" · archived" if lang == "en" else " · archivada") if session.get("archived_at") else ""
            top_left.markdown(f"**#{session['id']}** · {created_word} {_local(session['created_at'])}{archived_word}")
            with top_right.popover("Options" if lang == "en" else "Opciones", icon=":material/more_horiz:", width="stretch"):
                st.download_button("Export to Markdown" if lang == "en" else "Exportar a Markdown", history.export_markdown(session["id"]).encode("utf-8"),
                                   f"chat_{session['id']}.md", "text/markdown", icon=":material/download:", key="chat-export")
                if session.get("archived_at"):
                    if st.button("Restore conversation" if lang == "en" else "Restaurar conversación",
                                 icon=":material/unarchive:", key="chat-unarchive"):
                        history.set_archived(session["id"], False, SystemClock().now_iso())
                        st.session_state["chat-show-active"] = True
                        st.rerun()
                elif st.button("Archive conversation" if lang == "en" else "Archivar conversación",
                               icon=":material/archive:", key="chat-archive",
                               help=("Hides it from the list without deleting it." if lang == "en" else
                                     "La oculta de la lista sin borrarla.")):
                    history.set_archived(session["id"], True, SystemClock().now_iso())
                    st.session_state["chat_session_id"] = None
                    st.rerun()
                if st.button("Delete conversation" if lang == "en" else "Borrar conversación", icon=":material/delete:", type="primary", key="chat-delete"):
                    history.delete_session(session["id"])
                    st.session_state["chat_session_id"] = None
                    st.rerun()
            for message in session["messages"]:
                _show_message(message)
            with st.expander("Suggested questions" if lang == "en" else "Preguntas sugeridas", icon=":material/lightbulb:"):
                _suggestion_buttons(_chat_suggestions(query, lang), "chat-suggest-more")
        else:
            st.info("Type a question below or choose one of these to start a new conversation; previous ones are on the left."
                    if lang == "en" else
                    "Escriba una pregunta abajo o elija una de estas para empezar; las conversaciones anteriores están a la izquierda.")
            _suggestion_buttons(_chat_suggestions(query, lang), "chat-suggest")

    chat_input_ph = ("Ask about alerts, access, connections, files, persistence, or reputation"
                     if lang == "en" else
                     "Pregunta sobre alertas, accesos, conexiones, archivos, persistencia o reputación")
    prompt = st.chat_input(chat_input_ph) or st.session_state.pop("chat-pending", None)

    if prompt:
        from bootstrap import build_recorded_chat_service
        with conversation_col:
            with st.chat_message("user"): st.text(prompt)
            with st.spinner("Checking the local evidence..." if lang == "en" else "Consultando la evidencia local..."):
                try:
                    result = build_recorded_chat_service().ask(prompt, current, lang=lang)
                    st.session_state["chat_session_id"] = result["session_id"]
                except Exception as exc:
                    # The error is already stored in the conversation; keep it selected so it is visible
                    st.session_state["chat_session_id"] = getattr(exc, "session_id", current)
                    st.error(f"Chat local no disponible: {exc}")
                    return
        st.rerun()


def settings_page():
    settings, repository, _, _ = context(window_applies=False)
    lang = st.session_state.get("language") or "es"
    hero("⚙️ Ajustes", "Qué está activado en este equipo, cada cuánto se analiza, la base de datos y la bitácora técnica.", page_key="settings", lang=lang)
    features_tab, cycle_tab, data_tab, log_tab = st.tabs([
        ":material/toggle_on: " + ("Features" if lang == "en" else "Funciones"),
        ":material/schedule: " + ("Cycle" if lang == "en" else "Ciclo"),
        ":material/database: " + ("Database" if lang == "en" else "Base de datos"),
        ":material/bug_report: " + ("Technical Log" if lang == "en" else "Bitácora"),
    ])
    with features_tab:
        _features(settings)
    with cycle_tab:
        _link(LIVE_PAGE, "Source status and recent runs: Live" if lang == "en" else "Estado de las fuentes y ejecuciones recientes: En vivo", ":material/pulse_alert:")
        _automation_settings(settings)
    with data_tab:
        status = repository.status()
        a, b = st.columns(2)
        a.metric("Database size" if lang == "en" else "Tamaño de la base", f"{status['database_bytes'] / 1_048_576:.1f} MB")
        b.metric("Saved alerts" if lang == "en" else "Alertas guardadas", status["tables"].get("alerts", 0))
        st.markdown("**Rows per table**" if lang == "en" else "**Filas por tabla**")
        frame = pd.DataFrame([{"tabla": name, "filas": count} for name, count in status["tables"].items()])
        chart(_style(px.bar(frame.sort_values("filas"), x="filas", y="tabla", orientation="h",
                            labels={"tabla": "", "filas": ""}), 380), key="state-tables")
        _state_maintenance(repository, settings)
    with log_tab:
        _error_log()



@st.cache_data(ttl=30, show_spinner=False)
def _cycle_task() -> dict:
    from infrastructure.windows.system_features import cycle_task_status
    return cycle_task_status()


def _feature(title: str, description: str, status: str, value: bool, key: str, disabled: bool = False) -> bool | None:
    """One switch tied to the real state: returns the new value when the person flips it, else None.

    The key includes the current state, so after an action (or a change made outside Atalaya) the switch shows
    what is really configured, not what was last clicked.
    """
    with st.container(border=True):
        left, right = st.columns([6, 1], vertical_alignment="center")
        left.markdown(f"**{title}**")
        left.caption(description)
        left.markdown(status)
        widget = f"feature-{key}-{value}"
        new = right.toggle(title, value=value, key=widget, label_visibility="collapsed", disabled=disabled)
    if new == value:
        return None
    # Forget the click: the next run redraws the switch from the real state, so an action that reports success
    # without taking effect cannot make the page repeat it forever
    del st.session_state[widget]
    return new


def _features(settings):
    from dataclasses import replace

    from bootstrap import build_automation_config_service
    from infrastructure.windows import system_features as system

    automation = build_automation_config_service(settings)
    config = automation.load()

    def save(**changes):
        automation.save(replace(config, **changes))
        st.rerun()

    # Selector de idioma de la interfaz y modelos
    current_lang = st.session_state.get("language") or config.language or settings.language or "es"
    lang_options = ["es", "en"]
    lang_labels = {"es": "Español (Spanish)", "en": "English (Inglés)"}
    with st.container(border=True):
        col_l, col_r = st.columns([5, 2], vertical_alignment="center")
        col_l.markdown("**Language / Idioma**" if current_lang == "en" else "**Idioma / Language**")
        col_l.caption("Select the user interface language and LLM response instructions." if current_lang == "en" else "Seleccione el idioma para la interfaz de usuario y las instrucciones de los modelos LLM.")
        selected_lang = col_r.selectbox("Language", lang_options, index=lang_options.index(current_lang) if current_lang in lang_options else 0,
                                         format_func=lambda x: lang_labels.get(x, x), key="settings-lang-select", label_visibility="collapsed")
        if selected_lang != current_lang:
            st.session_state["language"] = selected_lang
            save(language=selected_lang)

    # Periodic analysis: the Windows scheduled task, not a preference
    task = _cycle_task()
    if task.get("enabled"):
        next_run = to_local_datetime(task.get("next")) if task.get("next") else None
        status = (f":green[● Activo] · cada {task.get('minutes') or config.cycle_minutes} min"
                  + (f" · próxima ejecución {next_run:%d/%m %H:%M}" if isinstance(next_run, datetime) else ""))
        if not task.get("windowless"):
            status += " · :orange[la tarea abre una consola: desactive y vuelva a activar para corregirlo]"
    else:
        status = ":orange[● Desactivado]: Atalaya solo recolecta cuando pulsa «Recolectar»." + (
            f" ({task['error']})" if task.get("error") else "")
    changed = _feature("Análisis periódico", f"Una tarea programada de Windows recolecta y analiza cada "
                       f"{config.cycle_minutes} min mientras haya sesión iniciada (el intervalo se cambia en Ciclo).",
                       status, bool(task.get("enabled")), "cycle")
    if changed is not None:
        with st.spinner("Actualizando la tarea programada…"):
            ok, message = system.set_cycle_task(changed, config.cycle_minutes)
        _cycle_task.clear()
        (st.success if ok else st.error)(message or ("Hecho" if ok else "No se pudo cambiar la tarea"))
        if ok:
            st.rerun()

    startup = system.startup_enabled()
    monitor = system.file_monitor_running()
    changed = _feature("Iniciar con Windows", "Al iniciar sesión, Atalaya arranca junto al reloj con la vigilancia de "
                       "archivos (detecta cambios masivos al momento, sin esperar al ciclo).",
                       (":green[● Activado]" if startup else ":gray[● Desactivado]")
                       + " · vigilancia de archivos " + (":green[en marcha ahora]" if monitor else
                                                         ":gray[apagada ahora] (se enciende desde el icono junto al reloj)"),
                       startup, "startup")
    if changed is not None:
        ok, message = system.set_startup(changed)
        (st.success if ok else st.error)(message or ("Hecho" if ok else "No se pudo cambiar el inicio automático"))
        if ok:
            st.rerun()

    changed = _feature("Analizar cuando haya novedades", "Tras cada recolección con datos nuevos, aplica las reglas "
                       f"R01–R{len(ALL_RULES):02d} y crea alertas.", ":green[● Activado]" if config.automatic_analysis else
                       ":orange[● Desactivado]: se recolecta, pero no se crean alertas hasta pulsar «Analizar».",
                       config.automatic_analysis, "rules")
    if changed is not None:
        save(automatic_analysis=changed)

    _rule_settings(settings)

    changed = _feature("Explicar alertas con IA", "La IA local agrupa y explica las alertas nuevas. Sin ella, las reglas "
                       "siguen funcionando.", ":green[● Activado]" if config.use_llm else ":gray[● Desactivado]",
                       config.use_llm, "llm")
    if changed is not None:
        save(use_llm=changed)

    changed = _feature("Resúmenes automáticos por sección", "Un resumen de la IA por turno, para no saturar la GPU; "
                       "también se pueden pedir con «Resumir ahora».",
                       (":green[● Activado]" if config.section_summaries else ":gray[● Desactivado]")
                       + ("" if config.use_llm else " · requiere «Explicar alertas con IA»"),
                       config.section_summaries, "summaries", disabled=not config.use_llm)
    if changed is not None:
        save(section_summaries=changed)

    changed = _feature("Backup diario", "Una copia consistente de la base de datos al día, en la carpeta de backups.",
                       ":green[● Activado]" if config.backup_daily else ":gray[● Desactivado]", config.backup_daily,
                       "backup")
    if changed is not None:
        save(backup_daily=changed)

    changed = _feature("Avisos de red en vivo", "Notificación de Windows cuando alguien de la red local o de Internet se "
                       "conecta a un servidor de este equipo, le hace ping o escanea sus puertos, y cuando un servidor "
                       "nuevo queda expuesto. Requiere Atalaya junto al reloj; todo queda también en Desarrollo.",
                       ":green[● Activado]" if config.network_notifications else
                       ":gray[● Desactivado]: se siguen registrando en Desarrollo, sin notificar.",
                       config.network_notifications, "network")
    if changed is not None:
        save(network_notifications=changed)
    with st.container(border=True):
        st.markdown("**IPs de confianza**")
        st.caption("No generan avisos de red (p. ej. su celular o su NAS). Separe con comas; admite redes como "
                   "192.168.1.0/24. Se aplica en menos de un minuto.")
        left, right = st.columns([5, 1], vertical_alignment="bottom")
        trusted = left.text_input("IPs de confianza", value=config.trusted_ips, key="trusted-ips",
                                  placeholder="192.168.1.50, 192.168.1.0/24", label_visibility="collapsed")
        if right.button("Guardar", key="trusted-save", width="stretch", disabled=trusted == config.trusted_ips):
            try:
                save(trusted_ips=trusted.strip())
            except ValueError as exc:
                st.error(str(exc))

    from application.doctor import _security_log_readable
    from infrastructure.windows.live_network import firewall_readable
    readable, _ = _security_log_readable()
    firewall = firewall_readable(settings.firewall_log_path)
    with st.container(border=True):
        left, right = st.columns([5, 2], vertical_alignment="center")
        left.markdown("**Permisos ampliados**")
        left.caption("Leer los accesos (registro Security) y el log del firewall sin ejecutar Atalaya como "
                     "administrador. Se configura una vez y Windows pide confirmación.")
        left.markdown(f"Accesos: {':green[legibles]' if readable else ':orange[sin permiso]'} · "
                      f"Firewall: {':green[registro legible]' if firewall else ':orange[sin registro o sin permiso de lectura]'}")
        if right.button("Configurar permisos", icon=":material/admin_panel_settings:", width="stretch",
                        key="feature-permissions", disabled=readable and firewall):
            from infrastructure.windows.system_features import open_permissions_setup
            ok, message = open_permissions_setup()
            (st.info if ok else st.error)("Acepte el aviso de Windows y siga la consola que se abre."
                                          if ok else message)


def _rule_settings(settings):
    """Persistent per-rule switches; collecting evidence remains independent."""
    from application.rule_config import RULE_IDS
    from bootstrap import build_rule_config_service

    service = build_rule_config_service(settings)
    enabled = set(service.enabled_ids())
    with st.expander(f"Reglas de detección · {len(enabled)}/{len(ALL_RULES)} activas"):
        st.caption("Se aplican al próximo análisis. Desactivar una regla no detiene la recolección ni borra alertas "
                   "anteriores. Todas vienen activadas de forma predeterminada.")
        with st.form("detection-rules-config"):
            selected = []
            for rule_id in RULE_IDS:
                help_ = RULES[rule_id]
                if st.checkbox(f"{rule_id} · {help_.detects}", value=rule_id in enabled,
                               key=f"detection-rule-{rule_id}", help=help_.check):
                    selected.append(rule_id)
            left, right = st.columns(2)
            save_rules = left.form_submit_button("Guardar reglas", icon=":material/save:", width="stretch")
            enable_all = right.form_submit_button("Activar todas", icon=":material/select_all:", width="stretch")
        if save_rules or enable_all:
            chosen = RULE_IDS if enable_all else tuple(selected)
            service.save_enabled(chosen)
            if not chosen:
                st.warning("Todas las reglas quedaron desactivadas. Atalaya seguirá recolectando, pero no generará "
                           "alertas deterministas nuevas.")
            else:
                st.success(f"Configuración guardada: {len(chosen)} reglas activas.")
            st.rerun()


def _automation_settings(settings):
    from dataclasses import replace

    from bootstrap import build_automation_config_service, build_cycle_service
    automation = build_automation_config_service(settings)
    current = automation.load()
    with st.form("automation-config"):
        left, middle, right = st.columns(3)
        profile = left.selectbox("Perfil habitual", ["quick", "standard", "deep"],
                                 index=["quick", "standard", "deep"].index(current.profile),
                                 help="quick evita escaneos costosos; standard incluye archivos y persistencia.")
        window = middle.number_input("Ventana de análisis (horas)", 1, 720, current.analysis_window_hours)
        interval = right.number_input("Intervalo (minutos)", 1, 1440, current.cycle_minutes,
                                      help="Cada cuánto ejecuta la tarea programada el ciclo de recolección y análisis.")
        standard_every = left.number_input("Perfil standard cada N ciclos", 1, 10_000, current.standard_every_cycles)
        deep_every = middle.number_input("Perfil deep cada N ciclos", 1, 100_000, current.deep_every_cycles)
        retention = right.number_input("Retención (días)", 1, 3650, current.retention_days)
        if st.form_submit_button("Guardar", icon=":material/save:"):
            try:
                automation.save(replace(current, profile=profile, analysis_window_hours=int(window),
                                        cycle_minutes=int(interval), standard_every_cycles=int(standard_every),
                                        deep_every_cycles=int(deep_every), retention_days=int(retention)))
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success("Guardado. Los próximos ciclos usarán estos valores.")
                if int(interval) != current.cycle_minutes and _cycle_task().get("enabled"):
                    from infrastructure.windows.system_features import set_cycle_task
                    ok, message = set_cycle_task(True, int(interval))
                    _cycle_task.clear()
                    (st.success if ok else st.error)(f"Tarea programada: cada {int(interval)} min. {message}")
    col_run, col_note = st.columns([1, 3])
    if col_run.button("Ejecutar ciclo ahora", icon=":material/play_arrow:", width="stretch"):
        try:
            with st.spinner("Recolectando y evaluando novedades..."):
                cycle_result = build_cycle_service(settings).execute()
        except RuntimeError as exc:
            st.error(str(exc))
        else:
            analyzed = cycle_result.get("analyzed")
            st.success(f"Perfil {cycle_result['profile']}: {cycle_result['collected']['inserted']} filas nuevas; "
                       + (f"{analyzed['new_alerts']} alertas nuevas." if analyzed else "análisis omitido."))
    col_note.caption("El ciclo periódico lo ejecuta una tarea programada de Windows (Funciones → Análisis "
                     "periódico); el bloqueo interno impide ciclos simultáneos.")


def _state_maintenance(repository, settings):
    from bootstrap import build_automation_config_service
    current = build_automation_config_service(settings).load()
    st.markdown("**Mantenimiento**")
    if st.button("Crear backup", icon=":material/backup:"):
        from datetime import timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        st.success(str(repository.backup(repository.settings.backup_dir / f"atalaya_{stamp}.db")))
    confirm = st.checkbox(f"Confirmo que deseo aplicar la retención configurada de {current.retention_days} días")
    if st.button("Purgar", disabled=not confirm, icon=":material/delete_sweep:"):
        from datetime import timedelta, timezone
        st.json(repository.purge((datetime.now(timezone.utc) - timedelta(days=current.retention_days)).isoformat()))
        refresh_data()


# --- Primeros pasos --------------------------------------------------------------------------------

def getting_started():
    settings, _, _, _ = context(window_applies=False)
    lang = st.session_state.get("language") or "es"
    hero("🚀 Primeros pasos", "Qué necesita Atalaya en este equipo, qué falta y cómo resolverlo.", page_key="getting_started", lang=lang)
    from bootstrap import build_doctor_service
    doctor = build_doctor_service(settings)
    with st.spinner("Checking system prerequisites..." if lang == "en" else "Comprobando el equipo..."):
        checks = doctor.run()
    blocking = [check for check in checks if check.status == "fail"]
    warnings = [check for check in checks if check.status == "warn"]
    if blocking:
        st.error(f"{len(blocking)} issue(s) prevent using Atalaya. Resolve them first." if lang == "en" else f"{len(blocking)} problema(s) impiden usar Atalaya. Resuélvalos primero.")
    elif warnings:
        st.warning("Atalaya is working, but recommended improvements exist." if lang == "en" else "Atalaya funciona, pero hay mejoras recomendadas.")
    else:
        st.success("All set. Items marked optional expand what Atalaya can monitor." if lang == "en" else "Todo listo. Lo marcado como opcional amplía lo que Atalaya puede ver.")
    icons = {"ok": ":material/check_circle:", "warn": ":material/warning:", "fail": ":material/error:", "info": ":material/info:"}
    colors = {"ok": "green", "warn": "orange", "fail": "red", "info": "blue"}
    for group in dict.fromkeys(check.group for check in checks):
        st.subheader(group, divider="gray")
        for check in (c for c in checks if c.group == group):
            with st.container(border=True):
                left, right = st.columns([3, 2])
                left.markdown(f":{colors[check.status]}[{icons[check.status]}] **{check.title}**")
                left.text(check.detail)
                if check.fix:
                    right.caption(check.fix)
                if check.id in {"ollama", "model-chat", "model-embed"} and check.status != "ok":
                    with right:
                        _link(AI_PAGE, "Resolve in Local AI" if lang == "en" else "Resolver en IA local", ":material/tune:")
    with st.expander("Requirements and recommendations" if lang == "en" else "Requisitos y recomendaciones", icon=":material/menu_book:"):
        st.markdown(
            "- **Windows 10/11 (64-bit).**\n"
            "- **Ollama** (optional, recommended): without it there are deterministic rules and alerts, but no LLM explanations or chat.\n"
            "- **Analysis and chat model**: `qwen3.5:4b` (3.4 GB, ~6 GB free RAM). Low memory fallback: `qwen3.5:0.8b`.\n"
            "- **Embedding model** (optional): `embeddinggemma` (0.6 GB) improves local documentation search.\n"
            "- **Permissions** (optional): *Configure permissions* in Start Menu allows reading Security log and Firewall events without running Atalaya as Administrator.\n"
            "- Complete guide: `README/README.instalacion.md`."
            if lang == "en" else
            "- **Windows 10/11 de 64 bits.**\n"
            "- **Ollama** (opcional, recomendado): sin él hay reglas y alertas, pero no explicaciones ni chat.\n"
            "- **Modelo de análisis y chat**: `qwen3.5:4b` (3,4 GB, ~6 GB de RAM libre). Con poca memoria: `qwen3.5:0.8b`.\n"
            "- **Modelo de embeddings** (opcional): `embeddinggemma` (0,6 GB) mejora la búsqueda en la documentación.\n"
            "- **Permisos** (opcional, una vez): *Configurar permisos* en el menú Inicio permite leer accesos y el firewall "
            "sin ejecutar Atalaya como administrador.\n"
            "- Guía completa: `README/README.instalacion.md`.")


def processes():
    settings, _, query, since = context()
    lang = st.session_state.get("language") or "es"
    hero("⚙️ Procesos y RAM", "Consumo actual, evolución y ciclo de vida observados localmente.", page_key="processes", lang=lang)
    _section_summary(query, settings, "procesos")
    current = query.processes_current()
    if not current:
        empty("No process snapshots yet. Click Collect to create the first one." if lang == "en" else "Todavía no hay snapshots de procesos. Pulse Recolectar para crear el primero.")
        return
    for row in current:
        row["memoria_mb"] = round((row.get("private_bytes") or row.get("rss_bytes") or 0) / 1024 ** 2, 1)
        row["rss_mb"] = round((row.get("rss_bytes") or 0) / 1024 ** 2, 1)
    suspicious_dirs = ("\\temp\\", "\\downloads\\", "\\users\\public\\", "\\$recycle.bin\\")
    suspicious = [row for row in current if any(part in str(row.get("path") or "").replace("/", "\\").casefold()
                                                   for part in suspicious_dirs)]
    a, b, c, d = st.columns(4)
    a.metric("Active processes" if lang == "en" else "Procesos activos", len(current))
    b.metric("Attributed private memory" if lang == "en" else "Memoria privada atribuida", f"{sum(row['memoria_mb'] for row in current) / 1024:.1f} GB")
    c.metric(f"Processes ≥ {settings.process_high_memory_percent:.0f}% RAM" if lang == "en" else f"Procesos ≥ {settings.process_high_memory_percent:.0f}% RAM",
             sum(float(row.get("memory_percent") or 0) >= settings.process_high_memory_percent for row in current))
    d.metric("Paths to review" if lang == "en" else "Rutas a revisar", len(suspicious))
    st.caption("Private memory avoids double-counting shared pages; RSS is shown separately." if lang == "en" else "La memoria privada evita contar páginas compartidas varias veces; RSS se muestra por separado.")
    if suspicious:
        with st.expander("Processes in paths requiring review" if lang == "en" else "Procesos en rutas que requieren revisión", icon=":material/warning:"):
            table([{"proceso": row.get("name"), "pid": row.get("pid"), "padre": row.get("parent_name"),
                    "memoria MB": row["memoria_mb"], "ruta": row.get("path")}
                   for row in suspicious], key="processes-suspicious", windowed=False, columns=MEMORY_COLUMNS, lang=lang,
                  on_pick=lambda record: path_actions(record, "process-suspicious", lang))

    top = pd.DataFrame(current[:20])
    figure = px.bar(top.sort_values("memoria_mb"), x="memoria_mb", y="name", orientation="h",
                    hover_data=["pid", "rss_mb", "memory_percent", "path"],
                    text="memoria_mb", labels={"memoria_mb": "Private memory (MB)" if lang == "en" else "Memoria privada (MB)", "name": ""})
    figure.update_traces(texttemplate="%{x:,.0f} MB", textposition="outside", cliponaxis=False)
    chart(_style(figure, 520), key="process-memory-top")

    search = st.text_input("Filter by name, path, or user" if lang == "en" else "Filtrar por nombre, ruta o usuario", key="process-filter").casefold().strip()
    filtered = [row for row in current if not search or search in " ".join(
        str(row.get(key) or "") for key in ("name", "path", "process_user")).casefold()]
    table([{"proceso": row.get("name"), "pid": row.get("pid"), "privada MB": row["memoria_mb"],
            "RSS MB": row["rss_mb"], "% RAM": row.get("memory_percent"), "estado": row.get("status"),
            "usuario": row.get("process_user"), "padre": row.get("parent_name"), "ruta": row.get("path")}
           for row in filtered], key="processes-current", windowed=False, columns=MEMORY_COLUMNS, lang=lang,
          on_pick=lambda record: path_actions(record, "process-current", lang))

    st.subheader("History" if lang == "en" else "Historial", divider="gray")
    choices = {f"{row.get('name') or '?'} · PID {row['pid']} · {row['process_key'][:8]}": row["process_key"]
               for row in current}
    selected = st.selectbox("Process" if lang == "en" else "Proceso", list(choices), key="process-history-choice")
    history = query.process_history(since, choices[selected])
    if history:
        frame = pd.DataFrame(history)
        frame["hora"] = local_series(frame["ts"])
        frame["privada MB"] = frame["private_bytes"].fillna(frame["rss_bytes"]) / 1024 ** 2
        frame["RSS MB"] = frame["rss_bytes"] / 1024 ** 2
        chart(_time_axis(_style(px.line(frame, x="hora", y=["privada MB", "RSS MB"],
                                        labels={"value": "MB", "variable": "Metric" if lang == "en" else "Métrica", "hora": ""}), 340)),
              key="process-memory-history")

    st.subheader("Recently Ended" if lang == "en" else "Finalizados recientemente", divider="gray")
    ended = query.process_lifecycle(False, 250)
    table([{"proceso": row.get("name"), "pid": row.get("pid"), "inicio observado": row.get("first_seen"),
            "última observación": row.get("last_seen"), "fin inferido": row.get("ended_at"),
            "pico privado MB": round((row.get("peak_private_bytes") or 0) / 1024 ** 2, 1), "ruta": row.get("path")}
           for row in ended], key="processes-ended", windowed=False, columns=MEMORY_COLUMNS, lang=lang,
          on_pick=lambda record: path_actions(record, "process-ended", lang))



# --- Buscar ----------------------------------------------------------------------------------------

SEARCH_LABELS_ES = {"alerts": "Alertas", "connections": "Conexiones", "firewall_events": "Firewall", "auth_events": "Accesos",
                    "file_events": "Archivos", "ssh_observations": "SSH", "process_lifecycle": "Procesos",
                    "persistence_items": "Persistencia", "file_reputation": "Reputación"}
SEARCH_LABELS_EN = {"alerts": "Alerts", "connections": "Connections", "firewall_events": "Firewall", "auth_events": "Access",
                    "file_events": "Files", "ssh_observations": "SSH", "process_lifecycle": "Processes",
                    "persistence_items": "Persistence", "file_reputation": "Reputation"}
SEARCH_LABELS = SEARCH_LABELS_ES


def search():
    _, _, query, since = context()
    lang = st.session_state.get("language") or "es"
    labels = SEARCH_LABELS_EN if lang == "en" else SEARCH_LABELS_ES
    hero("🔎 Buscar", "Todo lo registrado sobre una IP, un proceso, una ruta, un hash o un usuario, en un solo lugar.", page_key="search", lang=lang)
    term = st.text_input("Buscar" if lang != "en" else "Search", value=st.query_params.get("q", ""), label_visibility="collapsed",
                         icon=":material/search:", placeholder="203.0.113.7 · powershell.exe · C:\\Users\\… · SHA-256 · username" if lang == "en" else "203.0.113.7 · powershell.exe · C:\\Users\\… · SHA-256 · usuario")
    st.caption("Partial matches, case-insensitive. Events are limited to the time window; processes, persistence, and reputation are full inventories."
               if lang == "en" else
               "Busca coincidencias parciales, sin distinguir mayúsculas. Los eventos se limitan a la ventana temporal; "
               "procesos, persistencia y reputación son inventarios y se buscan completos.")
    term = term.strip()
    # Keep the URL shareable, but only touch it when the term changes (rewriting it on load confuses the router)
    if not term:
        if "q" in st.query_params:
            del st.query_params["q"]
        return
    if st.query_params.get("q") != term:
        st.query_params["q"] = term
    try:
        results = query.entity_search(term, since)
    except ValueError as exc:
        return st.warning(str(exc))
    found = [(name, rows) for name, rows in results.items() if rows]
    if not found:
        return empty("No matches in the selected window. Try a substring or a longer window."
                     if lang == "en" else
                     "Nada coincide en la ventana seleccionada. Pruebe con parte del valor o una ventana más larga.")
    columns = st.columns(min(len(found), 5))
    for index, (name, rows) in enumerate(found):
        columns[index % len(columns)].metric(labels.get(name, name), f"{len(rows)}{'+' if len(rows) >= ENTITY_LIMIT else ''}")
    for tab, (name, rows) in zip(st.tabs([f"{labels.get(name, name)} ({len(rows)})" for name, rows in found]), found):
        with tab:
            if len(rows) >= ENTITY_LIMIT:
                st.caption(f"Showing the {ENTITY_LIMIT} most recent matches." if lang == "en" else f"Se muestran las {ENTITY_LIMIT} coincidencias más recientes.")
            if name == "alerts":
                for row in rows[:10]:
                    alert_lbl = f"{_severity_name(row['severity'], lang=lang)} · alert \\#{row['id']} · {row['rule_id']} · {_plain(row['title'])}" if lang == "en" else f"{_severity_name(row['severity'], lang=lang)} · alerta \\#{row['id']} · {row['rule_id']} · {_plain(row['title'])}"
                    _link("views/03_Alertas.py", alert_lbl, ":material/open_in_new:",
                          query_params={"id": row["id"]})
            table(rows, key=f"search-{name}", view=name if name in VIEWS else None,
                  windowed=name not in {"process_lifecycle", "persistence_items", "file_reputation"}, lang=lang,
                  on_pick=lambda record, section=name: path_actions(record, f"search-{section}", lang))



# --- Historial de análisis -------------------------------------------------------------------------

RISK_ORDER = ("low", "medium", "high", "critical")
HISTORY_KINDS = {"todos": "Todos", "alertas": "Análisis de alertas", "seccion": "Resúmenes por sección"}
HISTORY_PAGE_SIZE = 10
FAILED = "Fallido"


def _history_title(item: dict) -> str:
    from application.section_summaries import SECTIONS
    return "Análisis de alertas" if item["kind"] == "alertas" else f"Resumen · {SECTIONS.get(item['section'], item['section'])}"


def _risk_name(risk: str | None) -> str:
    return SEVERITY_NAMES.get(risk, FAILED) if risk else FAILED


def _risk_pill(risk: str | None) -> str:
    """Coloured badge; only fixed labels and palette colours reach the HTML."""
    color = SEVERITY_COLORS.get(risk, "#94A3B8") if risk in RISK_ORDER else "#94A3B8"
    return f'<span class="nl-pill" style="--c:{color}">{_risk_name(risk if risk in RISK_ORDER else None)}</span>'


def _history_charts(items: list[dict]):
    from application.section_summaries import SECTIONS

    frame = pd.DataFrame([{"Fecha": to_local_datetime(item["ts"]), "Riesgo": _risk_name(item["risk"]),
                           "Tipo": "Alertas" if item["kind"] == "alertas" else "Sección",
                           "Fila": "Alertas" if item["kind"] == "alertas" else SECTIONS.get(item["section"], item["section"]),
                           "Modelo": item["model"] or "?", "duracion": (item["duration_ms"] or 0) / 1000,
                           # Plotly renders a subset of HTML in hovers: escape the LLM text
                           "Resumen": network.safe(item["summary"] or item["error"] or "", 140)} for item in items])
    colors = {SEVERITY_NAMES[level]: SEVERITY_COLORS[level] for level in RISK_ORDER} | {FAILED: "#94A3B8"}
    order = [SEVERITY_NAMES[level] for level in RISK_ORDER] + [FAILED]

    st.markdown("**Riesgo a lo largo del tiempo** · ◆ análisis de alertas · ● resumen de una sección")
    figure = px.scatter(frame, x="Fecha", y="Riesgo", color="Riesgo", symbol="Tipo", custom_data=["Fila", "Modelo", "Resumen"],
                        color_discrete_map=colors, category_orders={"Riesgo": order[::-1]},
                        symbol_map={"Alertas": "diamond", "Sección": "circle"})
    figure.update_traces(marker=dict(size=13, line=dict(width=1.5, color="rgba(127,127,127,.6)")),
                         hovertemplate="<b>%{customdata[0]}</b> · %{y}<br>%{x|%d/%m/%Y %H:%M} · %{customdata[1]}"
                                       "<br>%{customdata[2]}<extra></extra>")
    # Every level stays on the axis, so "medium" always sits in the same place
    # Plotly stacks categories bottom-up: failures at the bottom, critical at the top
    shown_levels = ([FAILED] if (frame["Riesgo"] == FAILED).any() else []) + order[:-1]
    figure.update_yaxes(title=None, categoryorder="array", categoryarray=shown_levels,
                        range=[-0.5, len(shown_levels) - 0.5])
    chart(_time_axis(_style(figure, 300)).update_layout(showlegend=False), key="history-timeline")

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("**Riesgo por día y área** · color: el riesgo más alto del día · número: análisis")
        frame["Día"] = frame["Fecha"].dt.strftime("%d/%m")
        frame["nivel"] = frame["Riesgo"].map({name: index for index, name in enumerate(order[:-1])})
        days = sorted(frame["Fecha"].dt.normalize().unique())
        labels = [pd.Timestamp(day).strftime("%d/%m") for day in days]
        rows = ["Alertas"] + [name for name in SECTIONS.values() if name in set(frame["Fila"])]
        grid = (frame.dropna(subset=["nivel"]).groupby(["Fila", "Día"])["nivel"].max()
                .unstack().reindex(index=rows, columns=labels))
        counts = frame.groupby(["Fila", "Día"]).size().unstack().reindex(index=rows, columns=labels).fillna(0)
        scale = [[index / 3, SEVERITY_COLORS[level]] for index, level in enumerate(RISK_ORDER)]
        heat = go.Figure(go.Heatmap(
            z=grid.values, x=labels, y=rows, zmin=0, zmax=3, colorscale=scale, showscale=False, xgap=3, ygap=3,
            customdata=[[f"{SEVERITY_NAMES[RISK_ORDER[int(value)]] if value == value else 'Sin análisis'} · "
                         f"{int(count)} análisis" for value, count in zip(z_row, c_row)]
                        for z_row, c_row in zip(grid.values, counts.values)],
            text=[[str(int(count)) if count else "" for count in c_row] for c_row in counts.values],
            texttemplate="%{text}", textfont=dict(color="#13171F"),
            hovertemplate="%{y} · %{x}<br>%{customdata}<extra></extra>"))
        heat.update_yaxes(autorange="reversed")
        chart(_style(heat, 70 + 34 * len(rows)), key="history-heatmap")
    with right:
        st.markdown("**Análisis por día**")
        per_day = frame.groupby(["Día", "Riesgo"]).size().reset_index(name="total")
        bars = px.bar(per_day, x="Día", y="total", color="Riesgo", color_discrete_map=colors,
                      category_orders={"Riesgo": order, "Día": labels}, labels={"Día": "", "total": ""})
        bars.update_traces(hovertemplate="%{x} · %{y} análisis<extra>%{fullData.name}</extra>")
        chart(_style(bars, 70 + 34 * len(rows)), key="history-per-day")


def _history_card(item: dict):
    with st.container(border=True):
        when = format_local_datetime(item["ts"])
        st.markdown(f"{_risk_pill(item['risk'])} <b>{_history_title(item)}</b> · {when} · {_ago(item['ts'])}",
                    unsafe_allow_html=True)
        details = [_plain(item["model"] or "?"), "automático" if item["trigger"] == "auto" else "a petición"]
        if item["duration_ms"]:
            details.append(f"{item['duration_ms'] / 1000:.0f} s")
        if item["alerts"]:
            details.append(f"{item['alerts']} alerta(s) analizadas")
        if item["window_hours"]:
            details.append(f"ventana de {item['window_hours']} h")
        st.caption(" · ".join(details))
        if item["error"] and not item["result"]:
            st.text(f"El análisis falló: {item['error'][:300]}")
            return
        # LLM text is shaped by collected data: plain text, never Markdown/HTML
        st.text(item["summary"] or "")
        points = [point for point in item["points"] if point][:5]
        if points:
            st.text("\n".join(f"• {point}" for point in points))
        with st.expander("Detalle", icon=":material/unfold_more:"):
            if item["kind"] == "alertas":
                for incident in item["result"].get("incidents", []):
                    st.markdown(f"**{_severity_name(incident.get('severity', 'low'))}** · posible falso positivo: "
                                f"{SEVERITY_NAMES.get(incident.get('false_positive_likelihood'), '?').lower()}")
                    st.text(incident.get("title", ""))
                    st.text(incident.get("narrative", ""))
                    if incident.get("benign_explanations"):
                        st.text("Explicaciones benignas: " + "; ".join(incident["benign_explanations"]))
                    if incident.get("recommended_actions"):
                        st.text("Recomendaciones: " + "; ".join(incident["recommended_actions"]))
                    for alert_id in incident.get("alert_ids", [])[:6]:
                        _link("views/03_Alertas.py", f"Abrir la alerta \\#{int(alert_id)}", ":material/notification_important:",
                              query_params={"id": int(alert_id)})
                if not item["result"].get("incidents"):
                    st.caption("El modelo no agrupó las alertas en incidentes.")
            else:
                st.caption("Cifras agregadas que recibió el LLM para este resumen:")
                st.json(item["data"] or {}, expanded=False)


def analysis_history():
    _, _, query, since = context()
    lang = st.session_state.get("language") or "es"
    hero("🗂️ Historial de análisis", "Todo lo que concluyó el LLM local: análisis de alertas y resúmenes por sección, "
                                    "con su riesgo y su evolución.", page_key="history", lang=lang)
    from application.section_summaries import SECTIONS

    history_kinds_en = {"todos": "All", "alertas": "Alert analyses", "seccion": "Section summaries"}
    history_kinds = history_kinds_en if lang == "en" else HISTORY_KINDS

    a, b, c = st.columns([2, 3, 2], vertical_alignment="bottom")
    everything = a.toggle("Entire history" if lang == "en" else "Todo el historial", value=False, key="history-all",
                          help="Ignora la ventana temporal de la barra lateral y muestra todos los análisis guardados." if lang != "en" else "Ignore sidebar time window and show all saved analyses.")
    kind = b.segmented_control("Type" if lang == "en" else "Tipo", list(history_kinds), default="todos", format_func=history_kinds.get,
                               key="history-kind") or "todos"
    failed = c.toggle("Include failed" if lang == "en" else "Incluir fallidos", value=True, key="history-failed")
    d, e, f, g = st.columns([2, 2, 2, 3], vertical_alignment="bottom")
    items = query.analysis_history(None if everything else since)
    risks = d.multiselect("Risk" if lang == "en" else "Riesgo", list(RISK_ORDER), format_func=lambda s: _severity_name(s, lang=lang), key="history-risk",
                          placeholder="All" if lang == "en" else "Todos")
    sections = e.multiselect("Section" if lang == "en" else "Sección", list(SECTIONS), format_func=SECTIONS.get, key="history-section",
                             placeholder="All" if lang == "en" else "Todas", disabled=kind == "alertas")
    models = f.multiselect("Model" if lang == "en" else "Modelo", sorted({item["model"] for item in items if item["model"]}), key="history-model",
                           placeholder="All" if lang == "en" else "Todos")
    text = g.text_input("Search" if lang == "en" else "Buscar", key="history-text",
                        placeholder="IP, process, summary word…" if lang == "en" else "IP, proceso, palabra del resumen…",
                        icon=":material/search:").casefold().strip()

    items = [item for item in items
             if (kind == "todos" or item["kind"] == kind)
             and (failed or item["result"])
             and (not risks or item["risk"] in risks)
             and (not sections or item["kind"] == "alertas" and kind == "alertas" or item["section"] in sections)
             and (not models or item["model"] in models)
             and (not text or text in " ".join(str(value) for value in (item["summary"], item["model"], item["error"],
                                                                         *item["points"])).casefold())]
    if not items:
        return empty("No analyses with these filters. Analyses are generated by clicking Analyze, in the automated cycle, or via «Summarize now»."
                     if lang == "en" else
                     "No hay análisis con estos filtros. Los análisis se generan al pulsar Analizar, en el ciclo "
                     "automático o con «Resumir ahora» en cada sección.")

    finished = [item for item in items if item["result"]]
    latest = items[0]
    durations = [item["duration_ms"] / 1000 for item in items if item["duration_ms"]]
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Analyses" if lang == "en" else "Análisis", len(items), help="Análisis de alertas más resúmenes por sección en el periodo.")
    k2.metric("Latest risk" if lang == "en" else "Último riesgo", _risk_name(next((item["risk"] for item in finished), None)),
              help=f"{_history_title(latest)} · {_ago(latest['ts'], lang=lang)}")
    k3.metric("High or critical" if lang == "en" else "Altos o críticos", sum(item["risk"] in {"high", "critical"} for item in finished))
    k4.metric("Failed" if lang == "en" else "Fallidos", f"{len(items) - len(finished)}",
              help="Intentos en que el LLM no respondió o devolvió un formato inválido.")
    k5.metric("Avg duration" if lang == "en" else "Duración media", f"{sum(durations) / len(durations):.0f} s" if durations else "—",
              help="Solo análisis de alertas (los resúmenes no registran duración).")

    _history_charts(items)

    st.subheader("Chronology" if lang == "en" else "Cronología", divider="gray")
    pages = max(1, -(-len(items) // HISTORY_PAGE_SIZE))
    left, right = st.columns([3, 1], vertical_alignment="bottom")
    page_lbl = f"Page (of {pages})" if lang == "en" else f"Página (de {pages})"
    page = right.number_input(page_lbl, 1, pages, 1, key="history-page") if pages > 1 else 1
    left.caption((f"{len(items)} analyses, from newest to oldest" if lang == "en" else f"{len(items)} análisis, del más reciente al más antiguo")
                 + ((f" · page {page} of {pages}." if lang == "en" else f" · página {page} de {pages}.") if pages > 1 else "."))
    for item in items[(page - 1) * HISTORY_PAGE_SIZE: page * HISTORY_PAGE_SIZE]:
        _history_card(item)
    export = pd.DataFrame([{"fecha": format_local_datetime(item["ts"]), "tipo": _history_title(item),
                            "riesgo": _risk_name(item["risk"]), "modelo": item["model"], "origen": item["trigger"],
                            "resumen": item["summary"], "puntos": " | ".join(p for p in item["points"] if p),
                            "error": item["error"]} for item in items])
    st.download_button("Download CSV" if lang == "en" else "Descargar CSV", export.to_csv(index=False).encode("utf-8"),
                       csv_name("historial_analisis", False),
                       "text/csv", icon=":material/download:", key="history-csv")
