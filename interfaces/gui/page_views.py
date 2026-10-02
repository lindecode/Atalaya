from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from infrastructure.clock import SystemClock
from interfaces.gui.common import context
from interfaces.gui.components import empty, severity_label, table


def summary():
    st.title("Resumen")
    _, _, query, since = context()
    counts = query.counts(since)
    cols = st.columns(len(counts))
    for column, item in zip(cols, counts.items()): column.metric(item[0].replace("_", " ").title(), item[1])
    timeline = query.timeline(since)
    if timeline:
        st.plotly_chart(px.bar(pd.DataFrame(timeline), x="bucket", y="count", color="type", barmode="stack"), use_container_width=True)
    else: empty("Recolecte datos para ver la línea de tiempo.")


MAX_ALERTS_SHOWN = 100
BASELINE_RULES = {"R03", "R04", "R05", "R10"}


def _bulk_learn(repository):
    with st.expander("Aprender baseline (reducir falsos positivos)"):
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
    st.title("Alertas")
    _, repository, query, since = context()
    _bulk_learn(repository)
    rows = query.rows("alerts", since)
    if not rows: return empty("No hay alertas. Ejecute Analizar para aplicar R01–R14.")
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
            if a.button("Confirmar", key=f"confirm-{row['id']}"):
                repository.update_alert_status(row["id"], "confirmed", note or None, SystemClock().now_iso()); st.rerun()
            if b.button("Descartar", key=f"dismiss-{row['id']}"):
                repository.update_alert_status(row["id"], "dismissed", note or None, SystemClock().now_iso()); st.rerun()
            if row["rule_id"] in BASELINE_RULES and c.button("Aprobar como normal", key=f"approve-{row['id']}"):
                repository.approve_alert(row["id"], SystemClock().now_iso()); st.rerun()


def generic(title, table_name, message):
    st.title(title)
    _, _, query, since = context()
    table(query.rows(table_name, since), key=table_name)
    if not query.rows(table_name, since, 1): st.caption(message)


def connections(): generic("Conexiones", "connections", "Ejecute Recolectar para obtener conexiones y puertos en escucha.")
def access(): generic("Accesos", "auth_events", "El registro Security requiere permisos de administrador.")
def files(): generic("Archivos", "file_events", "Ejecute Recolectar o Watch para observar archivos.")
def persistence(): generic("Persistencia", "persistence_items", "Ejecute Recolectar para inventariar Run, Startup, tareas y servicios.")
def firewall(): generic("Firewall", "firewall_events", "Active el registro de paquetes descartados en la Fase 4.")


def reports():
    st.title("Informes")
    settings, _, _, _ = context()
    paths = sorted(settings.reports_dir.glob("*.md"), reverse=True) if settings.reports_dir.exists() else []
    if not paths: return empty("No hay informes. Ejecute el comando report.")
    chosen = st.selectbox("Informe", paths, format_func=lambda p: p.name)
    content = chosen.read_text(encoding="utf-8")
    # The report embeds LLM text: rendering it as Markdown would let an injected ![](http://...) leak data off the machine
    st.code(content, language="markdown")
    st.download_button("Descargar", content.encode("utf-8"), chosen.name, "text/markdown")


def chat():
    st.title("Chat")
    from interfaces.gui.common import model_selector
    model = model_selector()
    if model and not model["tools"]:
        st.warning(f"{model['name']} no admite tool calling; elija en la barra lateral un modelo con tools para el chat.")
    from bootstrap import build_rag_service
    rag_status = build_rag_service(lexical_only=True).status()
    st.caption(f"Conocimiento local: {rag_status['chunks']} chunks; {rag_status['embedded']} con embeddings")
    with st.expander("Índice RAG local"):
        use_embeddings = st.checkbox("Generar embeddings con Ollama", value=True)
        if st.button("Indexar documentación confiable"):
            with st.status("Indexando documentación local...") as index_status:
                result = build_rag_service(lexical_only=not use_embeddings).index()
                index_status.update(label=f"Indexados {result['chunks']} chunks", state="complete")
                if result["embedding_error"]: st.warning(result["embedding_error"])
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
    st.title("Estado")
    _, repository, query, _ = context()
    status = repository.status()
    st.json(status)
    st.subheader("Ejecuciones")
    table(query.rows("runs", None, 100), key="runs")
    st.subheader("Mantenimiento")
    if st.button("Crear backup"):
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        st.success(str(repository.backup(repository.settings.backup_dir / f"network_llm_{stamp}.db")))
    confirm = st.checkbox("Confirmo que deseo aplicar la retención de 30 días")
    if st.button("Purgar", disabled=not confirm):
        from datetime import datetime, timedelta, timezone
        st.json(repository.purge((datetime.now(timezone.utc) - timedelta(days=30)).isoformat()))
