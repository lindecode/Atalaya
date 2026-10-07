from __future__ import annotations

import ipaddress
import json
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from domain.rules.catalog import ALL_RULES
from infrastructure.clock import SystemClock
from infrastructure.sqlite.queries import ENTITY_LIMIT, ROWS_LIMIT
from interfaces.gui import network
from interfaces.gui.common import context, refresh_data
from interfaces.gui.components import (SEVERITY_COLORS, SEVERITY_ICONS, SEVERITY_NAMES, chart, empty, hero, legend,
                                       page_link, plain_label, risk_banner, search_links, severity_label, table)
from interfaces.gui.chart_data import hourly_frame
from interfaces.gui.rule_help import OPEN_STATUSES, RULES, STATUS_NAMES
from interfaces.gui.table_formatting import COLUMN_FORMAT, format_local_datetime, local_series, to_local_datetime
from interfaces.gui.table_views import EVENT_NAMES, VIEWS, evidence_view


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


# --- Panel -----------------------------------------------------------------------------------------

def overview():
    settings, _, query, since = context()
    hero("🛡️ Panel de seguridad", "Qué pasa ahora en este equipo: alertas abiertas, tráfico de red y exposición.")
    severities = query.open_alerts_by_severity()
    analysis = query.latest_analysis()
    last_collect = query.last_run("collect")
    rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    worst = next((level for level in ("critical", "high", "medium", "low") if severities.get(level)), "low")
    llm_level = analysis["result_json"]["overall_risk"] if analysis and analysis.get("result_json") else "low"
    level = max(worst, llm_level, key=rank.get)
    open_total = sum(severities.values())
    risk_banner(level, f"{open_total} alerta(s) abierta(s) · última recolección: {_local((last_collect or {}).get('started_at'))}")

    snapshot = query.connections(since, latest_only=True)
    flows = network.active_flows(snapshot)
    exposed = [item for item in network.exposure(snapshot) if item["alcance"] == "Toda la red"]
    a, b, c, d, e = st.columns(5)
    a.metric("Alertas críticas/altas", severities.get("critical", 0) + severities.get("high", 0))
    b.metric("Salientes activas", sum(row["direction"] == "outbound" for row in flows))
    c.metric("Entrantes activas", sum(row["direction"] == "inbound" for row in flows))
    d.metric("Puertos abiertos a la red", len(exposed))
    e.metric("Destinos distintos", len({row["raddr"] for row in flows if row["direction"] == "outbound"}))

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Tráfico ahora", divider="gray")
        if flows:
            legend(FLOW_LEGEND[:3])
            chart(network.flow_figure(network.build_flow(flows, max_remotes=8, suspicious_ports=settings.suspicious_ports), height=420),
                  key="overview-flow")
            _link("pages/3_Conexiones.py", "Ver el mapa completo de conexiones", ":material/hub:")
        else:
            empty("Sin conexiones activas con el exterior en la última recolección. Pulse Recolectar.")
    with right:
        st.subheader("Alertas abiertas", divider="gray")
        if severities:
            # A few categories compared by size: labelled bars read faster than a donut
            frame = pd.DataFrame([{"nivel": SEVERITY_NAMES[s], "total": severities[s]}
                                  for s in ("low", "medium", "high", "critical") if severities.get(s)])
            figure = px.bar(frame, x="total", y="nivel", orientation="h", color="nivel", text="total",
                            color_discrete_map={SEVERITY_NAMES[s]: c for s, c in SEVERITY_COLORS.items()},
                            labels={"nivel": "", "total": ""})
            figure.update_traces(textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{x}<extra></extra>")
            figure.update_xaxes(showticklabels=False, showgrid=False)
            chart(_style(figure, 50 + 42 * len(frame)).update_layout(showlegend=False), key="overview-severity")
            for alert in query.open_alerts(6):
                _link("pages/2_Alertas.py", f"{_severity_name(alert['severity'])} · \\#{alert['id']} {alert['rule_id']} · "
                      f"{_plain(alert['title'])}", ":material/chevron_right:", query_params={"id": alert["id"]})
            _link("pages/2_Alertas.py", "Revisar alertas", ":material/notification_important:")
        else:
            st.success("No hay alertas abiertas.")
        if analysis and analysis.get("result_json"):
            with st.expander(f"Resumen del LLM ({analysis['model']})", icon=":material/psychology:"):
                st.text(analysis["result_json"]["summary"])


# --- Operaciones en vivo -------------------------------------------------------------------------

def _age_label(value: str | None) -> tuple[str, str]:
    if not value:
        return "Sin datos", "inactive"
    observed = datetime.fromisoformat(value)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    seconds = max(0, int((datetime.now().astimezone() - observed.astimezone()).total_seconds()))
    if seconds < 60:
        text = f"hace {seconds} s"
    elif seconds < 3600:
        text = f"hace {seconds // 60} min"
    else:
        text = f"hace {seconds // 3600} h"
    return text, "fresh" if seconds <= 120 else "delayed" if seconds <= 900 else "stale"


def live_operations():
    _, _, query, since = context()
    hero("📡 Operaciones en vivo", "Estado actual y eventos recientes. El LLM no se ejecuta durante la actualización.")
    controls = st.columns([2, 2, 5])
    enabled = controls[0].toggle("Actualización automática", value=True, key="live-enabled")
    seconds = controls[1].selectbox("Intervalo", [2, 5, 10, 30], index=1, key="live-seconds",
                                    disabled=not enabled, format_func=lambda value: f"{value} segundos")
    controls[2].caption("Las consultas están limitadas y leen solo el estado actual y los 200 eventos más recientes.")
    event_types = st.multiselect("Tipos visibles", ["alerta", "conexión", "acceso", "archivo", "firewall", "ssh"],
                                 default=["alerta", "conexión", "acceso", "archivo", "firewall", "ssh"],
                                 key="live-types")

    @st.fragment(run_every=f"{seconds}s" if enabled else None)
    def current_state():
        status = query.live_status()
        alerts = status["alerts"]
        severe = alerts.get("critical", 0) + alerts.get("high", 0)
        process_age, _ = _age_label(status["process_ts"])
        connection_age, _ = _age_label(status["connection_ts"])
        a, b, c, d, e = st.columns(5)
        a.metric("Alertas críticas/altas", severe)
        b.metric("Procesos", status["processes"], help=f"Última observación: {process_age}")
        c.metric("RAM observada", f"{status['memory_bytes'] / (1024 ** 3):.1f} GB")
        d.metric("Conexiones actuales", status["connections"], help=f"Última observación: {connection_age}")
        e.metric("Puertos en escucha", status["listeners"])

        runs = query.live_runs(10)
        last = runs[0] if runs else None
        st.subheader("Ejecuciones y recolectores", divider="gray")
        if last:
            heartbeat, heartbeat_state = _age_label(last.get("heartbeat_at"))
            running = last["status"] == "running"
            if running and heartbeat_state == "stale":
                st.error(f"La ejecución #{last['id']} ({last['kind']}) parece bloqueada: latido {heartbeat}.")
            elif running:
                st.info(f"Ejecución #{last['id']} ({last['kind']}) activa · latido {heartbeat}.")
            elif last["status"] in {"error", "partial"}:
                st.warning(f"Última ejecución #{last['id']} ({last['kind']}): {last['status']} · terminó {heartbeat}.")
            else:
                st.success(f"Última ejecución #{last['id']} ({last['kind']}): {last['status']} · terminó {heartbeat}.")
            run_rows = [{"ID": run["id"], "Tipo": run["kind"], "Estado": run["status"],
                         "Inicio": format_local_datetime(run["started_at"]),
                         "Fin": format_local_datetime(run["finished_at"]),
                         "Administrador": "Sí" if run["is_admin"] else "No"} for run in runs]
            with st.expander("Historial y detalle de recolectores"):
                st.dataframe(pd.DataFrame(run_rows), hide_index=True, width="stretch", key="live-runs")
                latest_collect = next((run for run in runs if run["kind"] == "collect" and run["collectors"]), None)
                if latest_collect:
                    collector_rows = []
                    for name, detail in latest_collect["collectors"].items():
                        collector_rows.append({"Recolector": name, "Estado": detail.get("status", "?"),
                                               "Encontrados": detail.get("found", 0),
                                               "Insertados": detail.get("inserted", 0),
                                               "Avisos": "; ".join(map(str, detail.get("warnings", [])))})
                    st.dataframe(pd.DataFrame(collector_rows), hide_index=True, width="stretch",
                                 key="live-collectors")
        else:
            empty("Todavía no hay ejecuciones registradas.")

        st.subheader("Frescura de fuentes", divider="gray")
        freshness = []
        for source in query.live_freshness():
            age, state = _age_label(source["ultima_observacion"])
            freshness.append({"Fuente": source["fuente"], "Estado": state, "Actualizada": age,
                              "Fecha": format_local_datetime(source["ultima_observacion"])})
        st.dataframe(pd.DataFrame(freshness), hide_index=True, width="stretch", key="live-freshness",
                     column_config={"Estado": st.column_config.TextColumn(help="fresh ≤2 min; delayed ≤15 min; stale >15 min")})

        st.subheader("Flujo reciente", divider="gray")
        events = query.live_events(since, 200)
        if not events:
            empty("Todavía no hay eventos en la ventana seleccionada.")
        else:
            events = [event for event in events if event["tipo"] in event_types]
            if not events:
                return empty("No hay eventos de los tipos seleccionados.")
            frame = pd.DataFrame(events)
            frame["ts"] = local_series(frame["ts"])
            frame = frame.rename(columns={"ts": "Fecha", "tipo": "Tipo", "nivel": "Nivel",
                                          "resumen": "Resumen", "origen": "Origen", "entidad_id": "ID"})
            st.dataframe(frame, hide_index=True, width="stretch", key="live-events",
                         column_config={"Fecha": st.column_config.DatetimeColumn(format=COLUMN_FORMAT)})
            st.caption(f"Mostrando {len(events)} eventos recientes · fechas en hora local del equipo.")

    current_state()


# --- Actividad (antes Resumen) ---------------------------------------------------------------------

def summary():
    _, _, query, since = context()
    hero("📈 Actividad", "Volumen de eventos por hora y lo que concluyó el último análisis.")
    counts = query.counts(since)
    names = {"alerts": "Alertas", "auth_events": "Accesos", "connections": "Conexiones", "file_events": "Archivos",
             "persistence_items": "Persistencia nueva"}
    for column, (key, value) in zip(st.columns(len(counts)), counts.items()):
        column.metric(names.get(key, key), value)
    timeline = query.timeline(since)
    st.subheader("Eventos por hora", divider="gray")
    if timeline:
        # One row per event type with its own scale: hundreds of connections would otherwise flatten the alerts
        frame = hourly_frame(timeline, since, time_key="bucket", value_key="count", series_key="type")
        figure = px.bar(frame, x="bucket", y="count", color="type", facet_row="type",
                        labels={"bucket": "", "count": "", "type": ""})
        figure.update_yaxes(matches=None, title=None)
        figure.for_each_annotation(lambda note: note.update(text=note.text.split("=")[-1].capitalize(), textangle=0,
                                                            x=0, xanchor="left", y=note.y + 0.02, yanchor="bottom"))
        figure.update_traces(hovertemplate="%{x|%d/%m %H:%M} · %{y} eventos<extra>%{fullData.name}</extra>")
        types = frame["type"].nunique()
        chart(_time_axis(_style(figure, 70 + 120 * types), hourly_bars=True).update_layout(showlegend=False),
              key="activity-timeline")
    else:
        empty("Recolecte datos para ver la línea de tiempo.")
    analysis = query.latest_analysis()
    st.subheader("Último análisis del LLM", divider="gray")
    if analysis and analysis.get("result_json"):
        result = analysis["result_json"]
        risk_banner(result["overall_risk"], f"Modelo {analysis['model']} · {len(result.get('incidents', []))} incidente(s)")
        st.text(result["summary"])
        for incident in result.get("incidents", []):
            with st.expander(f"{severity_label(incident['severity'])} · {incident['title']}"):
                st.text(incident["narrative"])
                if incident.get("recommended_actions"):
                    st.text("Recomendaciones: " + "; ".join(incident["recommended_actions"]))
    else:
        empty("Todavía no hay un análisis del LLM. Pulse Analizar en la barra lateral.")


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


def _ip_profile(query, ip: str, since: str):
    """What this computer knows about one IP: scope, local DNS names, processes, ports and related evidence."""
    from infrastructure.windows.dns_cache import names_for

    found = query.entity_search(ip, since)
    exact = lambda rows, *fields: [row for row in rows if any(str(row.get(field) or "") == ip for field in fields)]
    conns = exact(found["connections"], "raddr", "laddr")
    blocked = exact(found["firewall_events"], "src_ip", "dst_ip")
    logons = exact(found["auth_events"], "source_ip")
    ssh = exact(found["ssh_observations"], "remote_address", "local_address")
    alerts = [row for row in found["alerts"] if f'"{ip}"' in str(row.get("evidence") or "") or ip == str(row.get("title"))]
    names = names_for(ip, _dns_records())
    with st.container(border=True):
        # `ip` went through ipaddress.ip_address: only digits, hex, dots and colons reach the Markdown
        st.markdown(f"#### :material/lan: {ip} · {network.SCOPE_LABELS.get(network.scope(ip), 'Desconocido')}")
        if names:
            st.text("Nombres que este equipo resolvió a esta IP: " + ", ".join(names[:8])
                    + (f" (+{len(names) - 8})" if len(names) > 8 else ""))
        else:
            st.caption("Sin nombres en la caché DNS local de Windows (se vacía con el tiempo y al reiniciar). "
                       "Atalaya no consulta servidores externos.")
        a, b, c, d, e = st.columns(5)
        a.metric("Conexiones", len(conns))
        b.metric("Procesos", len({network.process_label(row) for row in conns}))
        c.metric("Bloqueos del firewall", len(blocked))
        d.metric("Inicios de sesión", len(logons))
        e.metric("Alertas", len(alerts))
        if conns:
            ports = sorted({row.get("rport") if row.get("raddr") == ip else row.get("lport") for row in conns} - {None})
            seen = sorted(str(row["ts"]) for row in conns)
            st.text("Procesos: " + ", ".join(sorted({network.process_label(row) for row in conns}))[:400])
            st.text("Puertos y servicios: " + ", ".join(f"{port} ({network.service(port)})" for port in ports[:15]))
            st.text(f"Primera vez: {format_local_datetime(seen[0])} · última vez: {format_local_datetime(seen[-1])} "
                    "(en la ventana temporal)")
        if ssh:
            st.text(f"SSH: {len(ssh)} observación(es) con esta IP.")
        for alert in alerts[:5]:
            _link("pages/2_Alertas.py", f"{_severity_name(alert['severity'])} · alerta \\#{alert['id']} · {alert['rule_id']} · "
                  f"{_plain(alert['title'])}", ":material/notification_important:", query_params={"id": alert["id"]})
        _link("pages/13_Buscar.py", f"Ver todo lo registrado sobre {ip}", ":material/search:", query_params={"q": ip})


# --- Conexiones ------------------------------------------------------------------------------------

def connections():
    settings, _, query, since = context()
    hero("🌐 Conexiones", "Quién habla con este equipo (entrantes), con quién habla él (salientes) y qué puertos deja abiertos.")
    controls = st.columns([2, 1, 1, 1])
    mode = controls[0].segmented_control("Datos", ["Última recolección", "Toda la ventana"], default="Última recolección",
                                         key="net-mode")
    direction = controls[1].selectbox("Sentido", ["Ambos", "Entrantes", "Salientes"], key="net-direction")
    include_loopback = controls[2].toggle("Tráfico interno", value=False, key="net-loopback",
                                          help="Conexiones entre programas del propio equipo (127.0.0.1)")
    include_closing = controls[3].toggle("Cerrándose", value=False, key="net-closing",
                                         help="Incluye TIME_WAIT, CLOSE_WAIT y similares")
    ip_filter = st.text_input("Filtrar por IP", value=st.query_params.get("ip", ""), icon=":material/filter_alt:",
                              placeholder="Una IP completa (203.0.113.7) o parte de ella (192.168.)",
                              help="Filtra todas las pestañas por IP remota o local. Con una IP completa se muestra su perfil.")
    needle = ip_filter.strip()
    if needle != st.query_params.get("ip", ""):
        if needle:
            st.query_params["ip"] = needle
        elif "ip" in st.query_params:
            del st.query_params["ip"]
    rows = query.connections(since, latest_only=(mode != "Toda la ventana"))
    if needle:
        total = len(rows)
        rows = [row for row in rows if _ip_matches(row, needle)]
        st.caption(f"Filtrando por «{_plain(needle)}»: {len(rows)} de {total} conexiones.")
    if _valid_ip(needle):
        _ip_profile(query, _valid_ip(needle), since)
    if not rows:
        return empty("No hay conexiones que coincidan. Pruebe con «Toda la ventana» o quite el filtro de IP."
                     if needle else "No hay conexiones en la ventana. Pulse Recolectar en la barra lateral.")
    flows = network.active_flows(rows, include_loopback, include_closing)
    if direction != "Ambos":
        flows = [row for row in flows if row["direction"] == ("inbound" if direction == "Entrantes" else "outbound")]
    suspicious = [row for row in flows if network.is_suspicious(row, settings.suspicious_ports)]
    exposure = network.exposure(rows)

    a, b, c, d, e = st.columns(5)
    a.metric("Salientes", sum(row["direction"] == "outbound" for row in flows))
    b.metric("Entrantes", sum(row["direction"] == "inbound" for row in flows))
    c.metric("Procesos con red", len({network.process_label(row) for row in flows}))
    d.metric("Abiertos a toda la red", sum(item["alcance"] == "Toda la red" for item in exposure))
    e.metric("Sospechosas", len(suspicious))

    tab_flow, tab_exposure, tab_services, tab_time, tab_table = st.tabs(
        [":material/hub: Mapa de flujo", ":material/shield: Exposición", ":material/donut_large: Servicios",
         ":material/timeline: Evolución", ":material/table: Detalle"])
    with tab_flow:
        if flows:
            legend(FLOW_LEGEND)
            top = st.slider("IPs remotas por sentido", 4, 30, 12, key="net-top")
            flow = network.build_flow(flows, max_remotes=top, suspicious_ports=settings.suspicious_ports)
            chart(network.flow_figure(flow, height=max(460, 22 * len(flow.labels))), key="net-flow")
            st.caption("El grosor de cada banda es el número de conexiones. Las IP que no entran en el top se agrupan en «Otros». "
                       "Pase el ratón por una banda para ver puertos y servicios.")
        else:
            empty("No hay conversaciones con esos filtros. Pruebe a activar «Tráfico interno» o «Toda la ventana».")
    with tab_exposure:
        if exposure:
            legend([("Toda la red: cualquier equipo puede intentar conectar", network.COLORS["suspicious"]),
                    ("Una interfaz (LAN/VPN)", network.COLORS["inbound"]), ("Solo este equipo", network.COLORS["loopback"])])
            chart(network.exposure_figure(exposure), key="net-exposure")
            st.caption("Puertos TCP en escucha y UDP abiertos, agrupados por alcance y proceso. Haga clic para ampliar un grupo.")
        else:
            empty("No hay puertos en escucha en estos datos.")
    with tab_services:
        outbound = [row for row in flows if row["direction"] == "outbound"]
        if outbound:
            left, right = st.columns([3, 2])
            with left:
                chart(network.destinations_figure(outbound), key="net-services")
            with right:
                st.markdown("**Destinos más frecuentes**")
                top_dest = pd.DataFrame([{"destino": row["raddr"], "servicio": network.service(row.get("rport")),
                                          "alcance": network.SCOPE_LABELS.get(network.scope(row["raddr"]), "?")} for row in outbound])
                top_dest = top_dest.value_counts().reset_index(name="conexiones").head(12)
                st.dataframe(top_dest, hide_index=True, width="stretch")
        else:
            empty("No hay conexiones salientes con estos filtros.")
    with tab_time:
        all_rows = query.connections(since) if mode != "Toda la ventana" else rows
        if needle:
            all_rows = [row for row in all_rows if _ip_matches(row, needle)]
        points = network.timeline_rows(all_rows, include_loopback)
        if len({point["ts"] for point in points}) > 1:
            frame = pd.DataFrame(points)
            frame["ts"] = local_series(frame["ts"])
            figure = px.area(frame, x="ts", y="conexiones", color="sentido", markers=True,
                             color_discrete_map={"Entrantes": network.COLORS["inbound"], "Salientes": network.COLORS["outbound"]},
                             labels={"ts": "", "conexiones": "conexiones abiertas", "sentido": ""})
            chart(_time_axis(_style(figure, 360)), key="net-timeline")
            st.caption("Cada punto es una recolección. Un salto brusco de salientes merece una mirada al mapa de flujo.")
        else:
            empty("Hace falta más de una recolección en la ventana para ver la evolución.")
    with tab_table:
        detail = [{"sentido": {"inbound": "⬅ entrante", "outbound": "➡ saliente"}[row["direction"]],
                   "proceso": network.process_label(row), "remoto": row["raddr"], "puerto remoto": row.get("rport"),
                   "servicio": network.service(row.get("rport") if row["direction"] == "outbound" else row.get("lport")),
                   "alcance": network.SCOPE_LABELS.get(network.scope(row["raddr"]), "?"), "local": f"{row.get('laddr')}:{row.get('lport')}",
                   "estado": row.get("state"), "sospechosa": "⚠" if network.is_suspicious(row, settings.suspicious_ports) else "",
                   "ruta": row.get("process_path"), "hora": row.get("ts")} for row in flows]
        st.caption("Seleccione una conexión para ver el perfil de su IP remota.")
        table(detail, key="connections",
              on_pick=lambda row: _valid_ip(row.get("remoto")) and _ip_profile(query, _valid_ip(row["remoto"]), since))
    with st.expander("Sesiones y agentes SSH", icon=":material/terminal:"):
        ssh_rows = query.rows("ssh_observations", since, 1000)
        if ssh_rows:
            sessions = [row for row in ssh_rows if row["kind"] == "session"]
            services = [row for row in ssh_rows if row["kind"] == "service"]
            a, b, c = st.columns(3)
            a.metric("Sesiones observadas", len(sessions))
            b.metric("Túneles", sum(bool(row.get("tunnel_types")) for row in sessions))
            c.metric("Reenvío de agente", sum(row.get("agent_forwarding") == 1 for row in sessions))
            table(services + sessions, key="ssh_observations", view="ssh_observations")
        else:
            st.caption("Sin observaciones SSH. Pulse Recolectar para consultar sesiones, sshd y ssh-agent.")


# --- Alertas ---------------------------------------------------------------------------------------

MAX_ALERTS_SHOWN = 100
BASELINE_RULES = {"R03", "R04", "R05", "R06", "R07", "R10"}


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


def _severity_name(level: str) -> str:
    return f"{SEVERITY_ICONS.get(level, '⚪')} {SEVERITY_NAMES.get(level, level)}"


def _set_status(repository, alert_ids, status: str, note: str | None):
    now = SystemClock().now_iso()
    for alert_id in alert_ids:
        repository.update_alert_status(alert_id, status, note or None, now)
    refresh_data()


def _alert_detail(repository, query, row: dict):
    """Everything about one alert: what the rule means, its evidence, the LLM's view and the triage actions."""
    with st.container(border=True):
        st.markdown(f"#### {_severity_name(row['severity'])} · {row['rule_id']} · alerta #{row['id']}")
        st.text(f"{row['title']}  ·  {STATUS_NAMES.get(row['status'], row['status'])}  ·  "
                f"{format_local_datetime(row['ts'])}")
        if row.get("status_note"):
            st.text(f"Nota: {row['status_note']}")
        rule = RULES.get(row["rule_id"])
        if rule:
            left, right = st.columns(2)
            left.markdown("**Qué detecta**")
            left.write(rule.detects)
            right.markdown("**Qué revisar**")
            right.write(rule.check)
        try:
            summary = json.loads(row["evidence"]) if isinstance(row["evidence"], str) else row["evidence"]
        except ValueError:
            summary = {"evidencia": row["evidence"]}
        if isinstance(summary, dict) and summary:
            st.markdown("**Resumen de la evidencia**")
            st.dataframe(pd.DataFrame([{"campo": key, "valor": "" if value is None else str(value)}
                                       for key, value in summary.items()]), hide_index=True, width="stretch",
                         key=f"summary-{row['id']}")
            search_links(summary.values(), key=f"alert-{row['id']}")
        st.markdown("**Eventos que la originaron**")
        evidence = query.alert_evidence(row["id"])
        table(evidence, key=f"evidence-{row['id']}", view=evidence_view(evidence), windowed=False)
        for incident in query.llm_incidents_for(row["id"]):
            st.markdown(f"**Análisis del LLM** ({_plain(incident['model'])}) · severidad LLM: `{incident['severity']}` · "
                        f"posible falso positivo: `{incident['false_positive_likelihood']}`")
            # LLM text is shaped by collected data: show it as plain text, never as Markdown/HTML
            st.text(incident["narrative"])
            if incident.get("benign_explanations"):
                st.text("Explicaciones benignas: " + "; ".join(incident["benign_explanations"]))
            if incident.get("recommended_actions"):
                st.text("Recomendaciones: " + "; ".join(incident["recommended_actions"]))
        note = st.text_input("Nota", key=f"note-{row['id']}")
        a, b, c = st.columns(3)
        if a.button("Confirmar", key=f"confirm-{row['id']}", icon=":material/check_circle:"):
            _set_status(repository, [row["id"]], "confirmed", note); st.rerun()
        if b.button("Descartar", key=f"dismiss-{row['id']}", icon=":material/cancel:"):
            _set_status(repository, [row["id"]], "dismissed", note); st.rerun()
        if row["rule_id"] in BASELINE_RULES and c.button("Aprobar como normal", key=f"approve-{row['id']}",
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


def alerts():
    _, repository, query, since = context()
    hero("🚨 Alertas", "Lo que detectaron las reglas, con su evidencia y la explicación del LLM.")
    _bulk_learn(repository)
    rows = query.rows("alerts", since)
    _truncation_note(rows)
    requested = st.query_params.get("id")
    if not rows and not requested:
        return empty(f"No hay alertas. Pulse Analizar para aplicar las reglas R01–R{len(ALL_RULES):02d}.")
    open_rows = [row for row in rows if row["status"] in OPEN_STATUSES]
    labels = {"critical": "Críticas abiertas", "high": "Altas abiertas", "medium": "Medias abiertas", "low": "Bajas abiertas"}
    for column, (level, label) in zip(st.columns(4), labels.items()):
        column.metric(label, sum(row["severity"] == level for row in open_rows))
    a, b, c = st.columns(3)
    statuses = a.multiselect("Estado", list(STATUS_NAMES), default=list(OPEN_STATUSES), format_func=STATUS_NAMES.get,
                             key="alert-status", placeholder="Todos")
    severities = b.multiselect("Severidad", ["critical", "high", "medium", "low"], format_func=_severity_name,
                               key="alert-severity", placeholder="Todas")
    rules = c.multiselect("Regla", sorted({row["rule_id"] for row in rows}), key="alert-rule", placeholder="Todas",
                          format_func=lambda rule: f"{rule} · {RULES[rule].detects[:45]}…" if rule in RULES else rule)
    rows = [row for row in rows if (not statuses or row["status"] in statuses)
            and (not severities or row["severity"] in severities) and (not rules or row["rule_id"] in rules)]
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    rows.sort(key=lambda row: (rank.get(row["severity"], 4), row["ts"]))
    if len(rows) > MAX_ALERTS_SHOWN:
        st.caption(f"Mostrando {MAX_ALERTS_SHOWN} de {len(rows)} alertas; use los filtros para acotar.")
    rows = rows[:MAX_ALERTS_SHOWN]

    selected: list[dict] = []
    if rows:
        frame = pd.DataFrame([{"#": row["id"], "Severidad": _severity_name(row["severity"]), "Regla": row["rule_id"],
                               "Título": row["title"], "Resumen": _alert_summary(row["evidence"]),
                               "Estado": STATUS_NAMES.get(row["status"], row["status"]),
                               "Fecha": to_local_datetime(row["ts"])} for row in rows])
        event = st.dataframe(frame, hide_index=True, width="stretch", key="alerts-table", on_select="rerun",
                             selection_mode="multi-row",
                             column_config={"#": st.column_config.NumberColumn(format="%d", width="small"),
                                            "Fecha": st.column_config.DatetimeColumn(format=COLUMN_FORMAT)})
        st.caption("Seleccione una alerta para ver su detalle, o varias para actuar sobre todas a la vez.")
        selected = [rows[index] for index in (event.selection.rows if event else []) if index < len(rows)]
    else:
        empty("Ninguna alerta coincide con los filtros.")
    if len(selected) > 1:
        _bulk_actions(repository, selected)
        return
    target = selected[0] if selected else None
    if target is None and requested and str(requested).isdigit():
        target = query.alert(int(requested))  # a link from the Panel or a search, even outside these filters
    if target is None and rows:
        target = rows[0]
    if target:
        _alert_detail(repository, query, target)


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
    _, _, query, since = context()
    hero("🔑 Accesos", "Inicios de sesión, intentos fallidos, RDP y cambios de cuentas.")
    rows = query.rows("auth_events", since)
    _truncation_note(rows)
    if not rows:
        empty("Sin eventos de acceso. El registro Security necesita administrador o el grupo «Lectores del registro de eventos» "
              "(start\\configurar-permisos.bat).")
        return
    a, b, c, d = st.columns(4)
    a.metric("Inicios correctos", sum(row["event_id"] == 4624 for row in rows))
    b.metric("Intentos fallidos", sum(row["event_id"] == 4625 for row in rows))
    c.metric("RDP", sum(row["event_id"] == 1149 or (row["event_id"] == 4624 and row.get("logon_type") == 10) for row in rows))
    d.metric("Cambios de cuentas", sum(row["event_id"] in (4720, 4732) for row in rows))
    _hourly_chart(query, "auth_events", since, "event_id", EVENT_NAMES, key="auth")
    left, right = st.columns(2)
    with left: _top_chart(query, "auth_events", "source_ip", since, "Orígenes más frecuentes", key="auth-ip")
    with right: _top_chart(query, "auth_events", "target_user", since, "Cuentas más usadas", key="auth-user")
    with st.expander("Detalle", icon=":material/table:"):
        table(rows, key="auth_events", view="auth_events")


def files():
    _, _, query, since = context()
    hero("📁 Archivos", "Creaciones, cambios, renombrados y borrados en las carpetas vigiladas.")
    rows = query.rows("file_events", since)
    _truncation_note(rows)
    if not rows:
        empty("Sin eventos de archivos. Pulse Recolectar o ejecute start\\vigilar.bat.")
    else:
        a, b, c, d = st.columns(4)
        a.metric("Creados / nuevos", sum(row["action"] in ("created", "observed_new") for row in rows))
        b.metric("Modificados", sum(row["action"] in ("modified", "observed_changed") for row in rows))
        c.metric("Renombrados", sum(row["action"] == "moved" for row in rows))
        d.metric("Borrados", sum(row["action"] == "deleted" for row in rows))
        _hourly_chart(query, "file_events", since, "action", key="files")
        left, right = st.columns(2)
        with left: _top_chart(query, "file_events", "extension", since, "Extensiones", key="files-ext")
        with right: _top_chart(query, "file_events", "action", since, "Acciones", key="files-action")
        with st.expander("Detalle", icon=":material/table:"):
            table(rows, key="file_events", view="file_events")
    st.subheader("Reputación de ejecutables")
    reputations = query.rows("file_reputation", None, 100)
    table(reputations, key="file_reputation", view="file_reputation", windowed=False)
    st.caption("Sólo se consulta el SHA-256; nunca se carga el ejecutable. Ejecute "
               "`main.py reputation inspect RUTA --online` para enriquecer un archivo.")


def persistence():
    _, _, query, since = context()
    hero("🧩 Persistencia", "Lo que arranca solo: claves Run, carpeta Inicio, tareas programadas y servicios.")
    rows = query.rows("persistence_items", since)
    _truncation_note(rows)
    if not rows:
        return empty("Nada nuevo en la ventana. Pulse Recolectar para inventariar Run, Inicio, tareas y servicios.")
    names = {"run_key": "Claves Run", "startup_folder": "Carpeta Inicio", "scheduled_task": "Tareas", "service": "Servicios"}
    for column, (kind, label) in zip(st.columns(4), names.items()):
        column.metric(f"{label} (nuevos)", sum(row["kind"] == kind for row in rows))
    _top_chart(query, "persistence_items", "kind", since, "Elementos vistos por primera vez, por tipo", names, key="persistence")
    with st.expander("Detalle", icon=":material/table:"):
        table(rows, key="persistence_items", view="persistence_items")


def firewall():
    _, _, query, since = context()
    hero("🧱 Firewall", "Paquetes que el firewall de Windows bloqueó: quién intentó entrar y a qué puertos.")
    rows = query.rows("firewall_events", since)
    _truncation_note(rows)
    if not rows:
        empty("Sin eventos del firewall. Active el registro de paquetes bloqueados con start\\configurar-permisos.bat.")
        return
    a, b, c = st.columns(3)
    a.metric("Bloqueados", sum(row.get("action") == "DROP" for row in rows))
    b.metric("Orígenes distintos", len({row.get("src_ip") for row in rows}))
    c.metric("Puertos atacados", len({row.get("dst_port") for row in rows}))
    _hourly_chart(query, "firewall_events", since, "action", key="firewall")
    left, right = st.columns(2)
    with left: _top_chart(query, "firewall_events", "src_ip", since, "Orígenes más insistentes", key="fw-src")
    with right: _top_chart(query, "firewall_events", "dst_port", since, "Puertos más buscados",
                           {port: f"{port} · {name}" for port, name in network.SERVICES.items()}, key="fw-port")
    with st.expander("Detalle", icon=":material/table:"):
        table(rows, key="firewall_events", view="firewall_events")


# --- Herramientas ----------------------------------------------------------------------------------

def reports():
    settings, _, _, _ = context()
    hero("📄 Informes", "Informes Markdown generados por recolectar.bat o el comando report.")
    paths = sorted(settings.reports_dir.glob("*.md"), reverse=True) if settings.reports_dir.exists() else []
    if not paths: return empty("No hay informes. Ejecute start\\recolectar.bat o el comando report.")
    chosen = st.selectbox("Informe", paths, format_func=lambda p: p.name)
    content = chosen.read_text(encoding="utf-8")
    # The report embeds LLM text: rendering it as Markdown would let an injected ![](http://...) leak data off the machine
    st.code(content, language="markdown")
    st.download_button("Descargar", content.encode("utf-8"), chosen.name, "text/markdown", icon=":material/download:")


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
        # Answers are shaped by collected data and questions are free text: plain text only
        st.text(message["content"])
        details = [_local(message["ts"])]
        if message.get("model"): details.append(message["model"])
        if message.get("duration_ms"): details.append(f"{message['duration_ms'] / 1000:.1f} s")
        st.caption(" · ".join(details))
        if message.get("tool_calls"):
            with st.expander("Herramientas y evidencia consultadas"):
                st.json(message["tool_calls"])


def chat():
    context()
    hero("💬 Chat", "Pregunte en lenguaje natural sobre la evidencia recolectada y la documentación local. "
                    "Las conversaciones se guardan en la base local para consultarlas después.")
    from bootstrap import build_chat_history
    history = build_chat_history()
    model = st.session_state.get("llm_model_info")
    if model and not model["tools"]:
        st.warning(f"{model['name']} no admite tool calling; elija en la barra lateral un modelo con tools para el chat.")

    sessions_col, conversation_col = st.columns([1, 3], gap="large")
    with sessions_col:
        st.markdown("**Conversaciones**")
        if st.button("Nueva conversación", icon=":material/add_comment:", width="stretch", key="chat-new"):
            st.session_state["chat_session_id"] = None
        search = st.text_input("Buscar", placeholder="texto en preguntas o respuestas", key="chat-search",
                               label_visibility="collapsed")
        sessions = history.list_sessions(search or None, 50)
        if not sessions:
            st.caption("Sin conversaciones" + (" que coincidan." if search else " todavía."))
        current = st.session_state.get("chat_session_id")
        for session in sessions:
            label = f"{_plain(session['title'])}  \n{_local(session['updated_at'])} · {session['messages']} msj"
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
            top_left.markdown(f"**#{session['id']}** · creada {_local(session['created_at'])}")
            with top_right.popover("Opciones", icon=":material/more_horiz:", width="stretch"):
                st.download_button("Exportar a Markdown", history.export_markdown(session["id"]).encode("utf-8"),
                                   f"chat_{session['id']}.md", "text/markdown", icon=":material/download:", key="chat-export")
                if st.button("Borrar conversación", icon=":material/delete:", type="primary", key="chat-delete"):
                    history.delete_session(session["id"])
                    st.session_state["chat_session_id"] = None
                    st.rerun()
            for message in session["messages"]:
                _show_message(message)
        else:
            st.info("Escriba una pregunta abajo para empezar una conversación nueva, o abra una anterior a la izquierda.")

    prompt = st.chat_input("Pregunta sobre alertas, accesos, conexiones, archivos, persistencia o reputación")
    if prompt:
        from bootstrap import build_recorded_chat_service
        with conversation_col:
            with st.chat_message("user"): st.text(prompt)
            with st.spinner("Consultando la evidencia local..."):
                try:
                    result = build_recorded_chat_service().ask(prompt, current)
                    st.session_state["chat_session_id"] = result["session_id"]
                except Exception as exc:
                    # The error is already stored in the conversation; keep it selected so it is visible
                    st.session_state["chat_session_id"] = getattr(exc, "session_id", current)
                    st.error(f"Chat local no disponible: {exc}")
                    return
        st.rerun()


def state():
    settings, repository, query, _ = context()
    hero("⚙️ Estado", "Base de datos, ejecuciones y mantenimiento.")
    status = repository.status()
    a, b, c = st.columns(3)
    a.metric("Tamaño de la base", f"{status['database_bytes'] / 1_048_576:.1f} MB")
    b.metric("Alertas guardadas", status["tables"].get("alerts", 0))
    last = status.get("last_run") or {}
    c.metric("Última ejecución", f"{last.get('kind', '—')} · {_local(last.get('started_at'))}")
    collect = query.last_run("collect")
    if collect and collect.get("collectors"):
        import json
        st.subheader("Fuentes en la última recolección", divider="gray")
        detail = json.loads(collect["collectors"])
        icons = {"ok": "✅", "partial": "🟡", "skipped": "⏭️", "error": "❌"}
        table([{"fuente": name, "estado": f"{icons.get(info.get('status'), '')} {info.get('status')}",
                "nuevos": info.get("inserted"), "avisos": " · ".join(info.get("warnings", []))[:300]}
               for name, info in detail.items()], key="collectors", windowed=False, detail=False)
    st.subheader("Filas por tabla", divider="gray")
    frame = pd.DataFrame([{"tabla": name, "filas": count} for name, count in status["tables"].items()])
    chart(_style(px.bar(frame.sort_values("filas"), x="filas", y="tabla", orientation="h", labels={"tabla": "", "filas": ""}), 380),
          key="state-tables")
    st.subheader("Ejecuciones", divider="gray")
    table(query.rows("runs", None, 100), key="runs", view="runs", windowed=False)
    st.subheader("Modelos por función", divider="gray")
    from bootstrap import build_model_service
    model_service = build_model_service(settings)
    try:
        installed = model_service.available()
    except Exception as exc:
        st.warning(f"Ollama no disponible: {exc}")
    else:
        usable = [item for item in installed if item["chat"]]
        names = [item["name"] for item in usable]
        recommendations = model_service.recommendations()
        if names:
            columns = st.columns(3)
            for column, role, label in zip(columns, ("analysis", "chat", "summary"),
                                           ("Análisis estructurado", "Chat con herramientas", "Resúmenes")):
                current_model = model_service.current(role)
                selected = column.selectbox(label, names, index=names.index(current_model) if current_model in names else 0,
                                            key=f"model-role-{role}")
                recommended = recommendations.get(role)
                column.caption("Recomendado localmente: " + (recommended["name"] if recommended else "ninguno"))
                if selected != current_model: model_service.select(selected, role)
        embedding = recommendations.get("embedding")
        if embedding: st.caption(f"Embeddings recomendados: `{embedding['name']}`. La recomendación usa capacidades y tamaño instalados; valide con los evals locales.")
    st.subheader("Configuración de análisis automático", divider="gray")
    from application.automation import AutomationConfig
    from bootstrap import build_automation_config_service, build_cycle_service
    automation = build_automation_config_service(settings)
    current = automation.load()
    with st.form("automation-config"):
        left, middle, right = st.columns(3)
        profile = left.selectbox("Perfil habitual", ["quick", "standard", "deep"],
                                 index=["quick", "standard", "deep"].index(current.profile),
                                 help="quick evita escaneos costosos; standard incluye archivos y persistencia.")
        window = middle.number_input("Ventana de análisis (horas)", 1, 720, current.analysis_window_hours)
        interval = right.number_input("Intervalo recomendado (minutos)", 1, 1440, current.cycle_minutes)
        automatic = left.checkbox("Analizar cuando haya novedades", current.automatic_analysis)
        use_llm = middle.checkbox("Usar Ollama para explicar alertas", current.use_llm)
        backup_daily = right.checkbox("Backup diario recomendado", current.backup_daily)
        standard_every = left.number_input("Perfil standard cada N ciclos", 1, 10_000, current.standard_every_cycles)
        deep_every = middle.number_input("Perfil deep cada N ciclos", 1, 100_000, current.deep_every_cycles)
        retention = right.number_input("Retención (días)", 1, 3650, current.retention_days)
        if st.form_submit_button("Guardar configuración", icon=":material/save:"):
            try:
                automation.save(AutomationConfig(profile, int(window), automatic, use_llm, int(interval),
                                                   int(standard_every), int(deep_every), int(retention), backup_daily))
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success("Configuración guardada. Las tareas futuras usarán estos valores.")
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
    col_note.caption("Para periodicidad sin la GUI, Task Scheduler debe ejecutar `main.py cycle`; "
                     "el bloqueo interno impide ciclos simultáneos.")
    st.subheader("Mantenimiento", divider="gray")
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
    settings, _, _, _ = context()
    hero("🚀 Primeros pasos", "Qué necesita Atalaya en este equipo, qué falta y cómo resolverlo.")
    from bootstrap import build_doctor_service
    doctor = build_doctor_service(settings)
    with st.spinner("Comprobando el equipo..."):
        checks = doctor.run()
    blocking = [check for check in checks if check.status == "fail"]
    warnings = [check for check in checks if check.status == "warn"]
    if blocking:
        st.error(f"{len(blocking)} problema(s) impiden usar Atalaya. Resuélvalos primero.")
    elif warnings:
        st.warning("Atalaya funciona, pero hay mejoras recomendadas.")
    else:
        st.success("Todo listo. Lo marcado como opcional amplía lo que Atalaya puede ver.")
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
                if check.id in {"model-chat", "model-embed"} and check.status != "ok":
                    model = settings.ollama_embedding_model if check.id == "model-embed" else doctor.models.current()
                    if right.button(f"Descargar {model}", key=f"pull-{check.id}", icon=":material/download:"):
                        _pull_with_progress(doctor, model)
                if check.id == "ollama" and check.status != "ok" and "No instalado" in check.detail:
                    right.link_button("Descargar Ollama", "https://ollama.com/download/windows", icon=":material/open_in_new:")
    with st.expander("Requisitos y recomendaciones", icon=":material/menu_book:"):
        st.markdown(
            "- **Windows 10/11 de 64 bits.**\n"
            "- **Ollama** (opcional, recomendado): sin él hay reglas y alertas, pero no explicaciones ni chat.\n"
            "- **Modelo de análisis y chat**: `qwen3.5:4b` (3,4 GB, ~6 GB de RAM libre). Con poca memoria: `qwen3.5:0.8b`.\n"
            "- **Modelo de embeddings** (opcional): `embeddinggemma` (0,6 GB) mejora la búsqueda en la documentación.\n"
            "- **Permisos** (opcional, una vez): *Configurar permisos* en el menú Inicio permite leer accesos y el firewall "
            "sin ejecutar Atalaya como administrador.\n"
            "- Guía completa: `README/README.instalacion.md`.")


def processes():
    settings, _, query, since = context()
    hero("🧠 Procesos y RAM", "Consumo actual, evolución y ciclo de vida observados localmente.")
    current = query.processes_current()
    if not current:
        empty("Todavía no hay snapshots de procesos. Pulse Recolectar para crear el primero.")
        return
    for row in current:
        row["memoria_mb"] = round((row.get("private_bytes") or row.get("rss_bytes") or 0) / 1024 ** 2, 1)
        row["rss_mb"] = round((row.get("rss_bytes") or 0) / 1024 ** 2, 1)
    suspicious_dirs = ("\\temp\\", "\\downloads\\", "\\users\\public\\", "\\$recycle.bin\\")
    suspicious = [row for row in current if any(part in str(row.get("path") or "").replace("/", "\\").casefold()
                                                   for part in suspicious_dirs)]
    a, b, c, d = st.columns(4)
    a.metric("Procesos activos", len(current))
    b.metric("Memoria privada atribuida", f"{sum(row['memoria_mb'] for row in current) / 1024:.1f} GB")
    c.metric(f"Procesos ≥ {settings.process_high_memory_percent:.0f}% RAM",
             sum(float(row.get("memory_percent") or 0) >= settings.process_high_memory_percent for row in current))
    d.metric("Rutas a revisar", len(suspicious))
    st.caption("La memoria privada evita contar páginas compartidas varias veces; RSS se muestra por separado.")
    if suspicious:
        with st.expander("Procesos en rutas que requieren revisión", icon=":material/warning:"):
            table([{"proceso": row.get("name"), "pid": row.get("pid"), "padre": row.get("parent_name"),
                    "memoria MB": row["memoria_mb"], "ruta": row.get("path")}
                   for row in suspicious], key="processes-suspicious", windowed=False, columns=MEMORY_COLUMNS)

    top = pd.DataFrame(current[:20])
    figure = px.bar(top.sort_values("memoria_mb"), x="memoria_mb", y="name", orientation="h",
                    hover_data=["pid", "rss_mb", "memory_percent", "path"],
                    text="memoria_mb", labels={"memoria_mb": "Memoria privada (MB)", "name": ""})
    figure.update_traces(texttemplate="%{x:,.0f} MB", textposition="outside", cliponaxis=False)
    chart(_style(figure, 520), key="process-memory-top")

    search = st.text_input("Filtrar por nombre, ruta o usuario", key="process-filter").casefold().strip()
    filtered = [row for row in current if not search or search in " ".join(
        str(row.get(key) or "") for key in ("name", "path", "process_user")).casefold()]
    table([{"proceso": row.get("name"), "pid": row.get("pid"), "privada MB": row["memoria_mb"],
            "RSS MB": row["rss_mb"], "% RAM": row.get("memory_percent"), "estado": row.get("status"),
            "usuario": row.get("process_user"), "padre": row.get("parent_name"), "ruta": row.get("path")}
           for row in filtered], key="processes-current", windowed=False, columns=MEMORY_COLUMNS)

    st.subheader("Historial", divider="gray")
    choices = {f"{row.get('name') or '?'} · PID {row['pid']} · {row['process_key'][:8]}": row["process_key"]
               for row in current}
    selected = st.selectbox("Proceso", list(choices), key="process-history-choice")
    history = query.process_history(since, choices[selected])
    if history:
        frame = pd.DataFrame(history)
        frame["hora"] = local_series(frame["ts"])
        frame["privada MB"] = frame["private_bytes"].fillna(frame["rss_bytes"]) / 1024 ** 2
        frame["RSS MB"] = frame["rss_bytes"] / 1024 ** 2
        chart(_time_axis(_style(px.line(frame, x="hora", y=["privada MB", "RSS MB"],
                                        labels={"value": "MB", "variable": "Métrica", "hora": ""}), 340)),
              key="process-memory-history")

    st.subheader("Finalizados recientemente", divider="gray")
    ended = query.process_lifecycle(False, 250)
    table([{"proceso": row.get("name"), "pid": row.get("pid"), "inicio observado": row.get("first_seen"),
            "última observación": row.get("last_seen"), "fin inferido": row.get("ended_at"),
            "pico privado MB": round((row.get("peak_private_bytes") or 0) / 1024 ** 2, 1), "ruta": row.get("path")}
           for row in ended], key="processes-ended", windowed=False, columns=MEMORY_COLUMNS)


def _pull_with_progress(doctor, model: str):
    bar = st.progress(0.0, text=f"Descargando {model}...")
    try:
        for status, completed, total in doctor.pull_model(model):
            bar.progress(min(completed / total, 1.0) if total else 0.0, text=f"{model}: {status}")
    except Exception as exc:
        bar.empty()
        st.error(f"No se pudo descargar {model}: {exc}")
        return
    bar.progress(1.0, text=f"{model} descargado")
    st.cache_data.clear()
    st.rerun()


# --- Buscar ----------------------------------------------------------------------------------------

SEARCH_LABELS = {"alerts": "Alertas", "connections": "Conexiones", "firewall_events": "Firewall", "auth_events": "Accesos",
                 "file_events": "Archivos", "ssh_observations": "SSH", "process_lifecycle": "Procesos",
                 "persistence_items": "Persistencia", "file_reputation": "Reputación"}


def search():
    _, _, query, since = context()
    hero("🔎 Buscar", "Todo lo registrado sobre una IP, un proceso, una ruta, un hash o un usuario, en un solo lugar.")
    term = st.text_input("Buscar", value=st.query_params.get("q", ""), label_visibility="collapsed",
                         icon=":material/search:", placeholder="203.0.113.7 · powershell.exe · C:\\Users\\… · SHA-256 · usuario")
    st.caption("Busca coincidencias parciales, sin distinguir mayúsculas. Los eventos se limitan a la ventana temporal; "
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
        return empty("Nada coincide en la ventana seleccionada. Pruebe con parte del valor o una ventana más larga.")
    columns = st.columns(min(len(found), 5))
    for index, (name, rows) in enumerate(found):
        columns[index % len(columns)].metric(SEARCH_LABELS[name], f"{len(rows)}{'+' if len(rows) >= ENTITY_LIMIT else ''}")
    for tab, (name, rows) in zip(st.tabs([f"{SEARCH_LABELS[name]} ({len(rows)})" for name, rows in found]), found):
        with tab:
            if len(rows) >= ENTITY_LIMIT:
                st.caption(f"Se muestran las {ENTITY_LIMIT} coincidencias más recientes.")
            if name == "alerts":
                for row in rows[:10]:
                    _link("pages/2_Alertas.py", f"{_severity_name(row['severity'])} · alerta \\#{row['id']} · "
                          f"{row['rule_id']} · {_plain(row['title'])}", ":material/open_in_new:",
                          query_params={"id": row["id"]})
            table(rows, key=f"search-{name}", view=name if name in VIEWS else None,
                  windowed=name not in {"process_lifecycle", "persistence_items", "file_reputation"})
