from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from infrastructure.clock import SystemClock
from interfaces.gui import network
from interfaces.gui.common import context
from interfaces.gui.components import (SEVERITY_COLORS, SEVERITY_NAMES, chart, empty, hero, legend, risk_banner,
                                       severity_label, table)


FLOW_LEGEND = [("Entrante", network.COLORS["inbound"]), ("Saliente", network.COLORS["outbound"]),
               ("Proceso local", network.COLORS["process"]), ("IP de Internet", network.COLORS["public"]),
               ("IP de red local/VPN", network.COLORS["private"]), ("Sospechosa", network.COLORS["suspicious"])]
EVENT_NAMES = {4624: "Inicio de sesión", 4625: "Inicio fallido", 4648: "Credenciales explícitas", 4672: "Privilegios especiales",
               4698: "Tarea programada creada", 4720: "Usuario creado", 4732: "Añadido a grupo", 1102: "Log de auditoría borrado",
               1149: "Conexión RDP"}


def _local(ts: str | None) -> str:
    if not ts:
        return "nunca"
    return datetime.fromisoformat(ts).astimezone().strftime("%d/%m %H:%M")


def _link(page: str, label: str, icon: str):
    """Link to another page; when a page runs on its own (tests, direct run) there is no navigation to link to."""
    try:
        st.page_link(page, label=label, icon=icon)
    except Exception:
        st.caption(f"→ {label}")


def _style(figure, height: int = 320):
    figure.update_layout(height=height, margin=dict(l=8, r=8, t=10, b=8), paper_bgcolor="rgba(0,0,0,0)",
                         plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=-0.18, title=None))
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
            frame = pd.DataFrame([{"nivel": SEVERITY_NAMES[s], "total": severities[s]} for s in SEVERITY_COLORS if severities.get(s)])
            figure = px.pie(frame, names="nivel", values="total", hole=0.62, color="nivel",
                            color_discrete_map={SEVERITY_NAMES[s]: c for s, c in SEVERITY_COLORS.items()})
            figure.update_traces(textinfo="value", sort=False)
            chart(_style(figure, 230), key="overview-severity")
            for alert in query.open_alerts(6):
                st.text(f"{severity_label(alert['severity'])}  #{alert['id']} {alert['rule_id']} · {alert['title']}")
            _link("pages/2_Alertas.py", "Revisar alertas", ":material/notification_important:")
        else:
            st.success("No hay alertas abiertas.")
        if analysis and analysis.get("result_json"):
            with st.expander(f"Resumen del LLM ({analysis['model']})", icon=":material/psychology:"):
                st.text(analysis["result_json"]["summary"])


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
        frame = pd.DataFrame(timeline)
        frame["bucket"] = pd.to_datetime(frame["bucket"], utc=True).dt.tz_convert(None)
        chart(_style(px.bar(frame, x="bucket", y="count", color="type", barmode="stack",
                            labels={"bucket": "", "count": "eventos", "type": ""}), 360), key="activity-timeline")
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
    rows = query.connections(since, latest_only=(mode != "Toda la ventana"))
    if not rows:
        return empty("No hay conexiones en la ventana. Pulse Recolectar en la barra lateral.")
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
            chart(network.flow_figure(flow, height=max(460, min(1100, 26 * len(flow.labels)))), key="net-flow")
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
        points = network.timeline_rows(all_rows, include_loopback)
        if len({point["ts"] for point in points}) > 1:
            frame = pd.DataFrame(points)
            frame["ts"] = pd.to_datetime(frame["ts"], utc=True).dt.tz_convert(None)
            figure = px.area(frame, x="ts", y="conexiones", color="sentido", markers=True,
                             color_discrete_map={"Entrantes": network.COLORS["inbound"], "Salientes": network.COLORS["outbound"]},
                             labels={"ts": "", "conexiones": "conexiones abiertas", "sentido": ""})
            chart(_style(figure, 360), key="net-timeline")
            st.caption("Cada punto es una recolección. Un salto brusco de salientes merece una mirada al mapa de flujo.")
        else:
            empty("Hace falta más de una recolección en la ventana para ver la evolución.")
    with tab_table:
        detail = [{"sentido": {"inbound": "⬅ entrante", "outbound": "➡ saliente"}[row["direction"]],
                   "proceso": network.process_label(row), "remoto": row["raddr"], "puerto remoto": row.get("rport"),
                   "servicio": network.service(row.get("rport") if row["direction"] == "outbound" else row.get("lport")),
                   "alcance": network.SCOPE_LABELS.get(network.scope(row["raddr"]), "?"), "local": f"{row.get('laddr')}:{row.get('lport')}",
                   "estado": row.get("state"), "sospechosa": "⚠" if network.is_suspicious(row, settings.suspicious_ports) else "",
                   "ruta": row.get("process_path"), "hora": _local(row.get("ts"))} for row in flows]
        table(detail, key="connections")


# --- Alertas ---------------------------------------------------------------------------------------

MAX_ALERTS_SHOWN = 100
BASELINE_RULES = {"R03", "R04", "R05", "R10"}


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
            st.success(f"Aprobados {sum(counts.values())} elementos {counts}; {dismissed} alertas descartadas.")


def alerts():
    _, repository, query, since = context()
    hero("🚨 Alertas", "Lo que detectaron las reglas, con su evidencia y la explicación del LLM.")
    _bulk_learn(repository)
    rows = query.rows("alerts", since)
    if not rows: return empty("No hay alertas. Pulse Analizar para aplicar R01–R14.")
    open_rows = [row for row in rows if row["status"] in {"new", "analyzed"}]
    labels = {"critical": "Críticas abiertas", "high": "Altas abiertas", "medium": "Medias abiertas", "low": "Bajas abiertas"}
    for column, (level, label) in zip(st.columns(4), labels.items()):
        column.metric(label, sum(row["severity"] == level for row in open_rows))
    a, b, c = st.columns(3)
    statuses = a.multiselect("Estado", ["new", "analyzed", "confirmed", "dismissed"], default=["new", "analyzed"])
    severities = b.multiselect("Severidad", ["low", "medium", "high", "critical"])
    rules = c.multiselect("Regla", sorted({row["rule_id"] for row in rows}))
    rows = [row for row in rows if (not statuses or row["status"] in statuses)
            and (not severities or row["severity"] in severities) and (not rules or row["rule_id"] in rules)]
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    rows.sort(key=lambda row: (rank.get(row["severity"], 4), row["ts"]))
    if len(rows) > MAX_ALERTS_SHOWN:
        st.caption(f"Mostrando {MAX_ALERTS_SHOWN} de {len(rows)} alertas; use los filtros para acotar.")
    for row in rows[:MAX_ALERTS_SHOWN]:
        with st.expander(f"{severity_label(row['severity'])} · {row['rule_id']} · {row['title']} · #{row['id']} · {row['status']}"):
            st.code(row["evidence"], language="json")
            table(query.alert_evidence(row["id"]), key=f"evidence-{row['id']}")
            for incident in query.llm_incidents_for(row["id"]):
                st.markdown(f"**Análisis del LLM** ({incident['model']}) · severidad LLM: `{incident['severity']}` · "
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
                repository.update_alert_status(row["id"], "confirmed", note or None, SystemClock().now_iso()); st.rerun()
            if b.button("Descartar", key=f"dismiss-{row['id']}", icon=":material/cancel:"):
                repository.update_alert_status(row["id"], "dismissed", note or None, SystemClock().now_iso()); st.rerun()
            if row["rule_id"] in BASELINE_RULES and c.button("Aprobar como normal", key=f"approve-{row['id']}", icon=":material/verified:"):
                repository.approve_alert(row["id"], SystemClock().now_iso()); st.rerun()


# --- Evidencia -------------------------------------------------------------------------------------

def _hourly_chart(query, table_name: str, since: str, by: str | None, names: dict | None = None, key: str = ""):
    points = query.hourly(table_name, since, by)
    if not points:
        return
    frame = pd.DataFrame(points)
    frame["hora"] = pd.to_datetime(frame["hora"], utc=True).dt.tz_convert(None)
    if by:
        frame["serie"] = frame["serie"].map(lambda value: (names or {}).get(int(value) if value.isdigit() else value, value))
    figure = px.bar(frame, x="hora", y="total", color="serie" if by else None, labels={"hora": "", "total": "eventos", "serie": ""})
    chart(_style(figure, 300), key=f"hourly-{key}")


def _top_chart(query, table_name: str, column: str, since: str, title: str, names: dict | None = None, key: str = ""):
    items = query.grouped(table_name, column, since)
    st.markdown(f"**{title}**")
    if not items:
        return st.caption("Sin datos.")
    frame = pd.DataFrame(items)
    frame["valor"] = frame["valor"].map(lambda value: network.safe((names or {}).get(value, value), 40))
    figure = px.bar(frame.iloc[::-1], x="total", y="valor", orientation="h", labels={"valor": "", "total": ""})
    chart(_style(figure, 300), key=f"top-{key}")


def access():
    _, _, query, since = context()
    hero("🔑 Accesos", "Inicios de sesión, intentos fallidos, RDP y cambios de cuentas.")
    rows = query.rows("auth_events", since)
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
        table([{k: v for k, v in row.items() if k != "raw_xml"} | {"evento": EVENT_NAMES.get(row["event_id"], row["event_id"])}
               for row in rows], key="auth_events")


def files():
    _, _, query, since = context()
    hero("📁 Archivos", "Creaciones, cambios, renombrados y borrados en las carpetas vigiladas.")
    rows = query.rows("file_events", since)
    if not rows:
        return empty("Sin eventos de archivos. Pulse Recolectar o ejecute start\\vigilar.bat.")
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
        table(rows, key="file_events")


def persistence():
    _, _, query, since = context()
    hero("🧩 Persistencia", "Lo que arranca solo: claves Run, carpeta Inicio, tareas programadas y servicios.")
    rows = query.rows("persistence_items", since)
    if not rows:
        return empty("Nada nuevo en la ventana. Pulse Recolectar para inventariar Run, Inicio, tareas y servicios.")
    names = {"run_key": "Claves Run", "startup_folder": "Carpeta Inicio", "scheduled_task": "Tareas", "service": "Servicios"}
    for column, (kind, label) in zip(st.columns(4), names.items()):
        column.metric(f"{label} (nuevos)", sum(row["kind"] == kind for row in rows))
    _top_chart(query, "persistence_items", "kind", since, "Elementos vistos por primera vez, por tipo", names, key="persistence")
    with st.expander("Detalle", icon=":material/table:"):
        table(rows, key="persistence_items")


def firewall():
    _, _, query, since = context()
    hero("🧱 Firewall", "Paquetes que el firewall de Windows bloqueó: quién intentó entrar y a qué puertos.")
    rows = query.rows("firewall_events", since)
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
        table(rows, key="firewall_events")


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


def chat():
    context()
    hero("💬 Chat", "Pregunte en lenguaje natural sobre la evidencia recolectada y la documentación local.")
    model = st.session_state.get("llm_model_info")
    if model and not model["tools"]:
        st.warning(f"{model['name']} no admite tool calling; elija en la barra lateral un modelo con tools para el chat.")
    from bootstrap import build_rag_service
    rag_status = build_rag_service(lexical_only=True).status()
    st.caption(f"Conocimiento local: {rag_status['chunks']} chunks; {rag_status['embedded']} con embeddings")
    with st.expander("Índice RAG local", icon=":material/library_books:"):
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
    prompt = st.chat_input("Pregunta sobre alertas, accesos, conexiones, archivos o persistencia")
    if prompt:
        from bootstrap import build_chat_service
        with st.chat_message("user"): st.text(prompt)
        try:
            result = build_chat_service().ask(prompt)
            with st.chat_message("assistant"):
                st.text(result["answer"])
                with st.expander("Herramientas y evidencia"):
                    st.json(result["tool_calls"])
        except Exception as exc:
            st.error(f"Chat local no disponible: {exc}")


def state():
    _, repository, query, _ = context()
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
               for name, info in detail.items()], key="collectors")
    st.subheader("Filas por tabla", divider="gray")
    frame = pd.DataFrame([{"tabla": name, "filas": count} for name, count in status["tables"].items()])
    chart(_style(px.bar(frame.sort_values("filas"), x="filas", y="tabla", orientation="h", labels={"tabla": "", "filas": ""}), 380),
          key="state-tables")
    st.subheader("Ejecuciones", divider="gray")
    table(query.rows("runs", None, 100), key="runs")
    st.subheader("Mantenimiento", divider="gray")
    if st.button("Crear backup", icon=":material/backup:"):
        from datetime import timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        st.success(str(repository.backup(repository.settings.backup_dir / f"network_llm_{stamp}.db")))
    confirm = st.checkbox("Confirmo que deseo aplicar la retención de 30 días")
    if st.button("Purgar", disabled=not confirm, icon=":material/delete_sweep:"):
        from datetime import timedelta, timezone
        st.json(repository.purge((datetime.now(timezone.utc) - timedelta(days=30)).isoformat()))
