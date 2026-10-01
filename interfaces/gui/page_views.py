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


def alerts():
    st.title("Alertas")
    _, repository, query, since = context()
    rows = query.rows("alerts", since)
    if not rows: return empty("No hay alertas. Ejecute Analizar para aplicar R01–R14.")
    severities = st.multiselect("Severidad", ["low", "medium", "high", "critical"])
    if severities: rows = [row for row in rows if row["severity"] in severities]
    for row in rows:
        with st.expander(f"{severity_label(row['severity'])} · {row['rule_id']} · {row['title']} · #{row['id']}"):
            st.code(row["evidence"], language="json")
            table(query.alert_evidence(row["id"]), key=f"evidence-{row['id']}")
            note = st.text_input("Nota", key=f"note-{row['id']}")
            a, b = st.columns(2)
            if a.button("Confirmar", key=f"confirm-{row['id']}"):
                repository.update_alert_status(row["id"], "confirmed", note or None, SystemClock().now_iso()); st.rerun()
            if b.button("Descartar", key=f"dismiss-{row['id']}"):
                repository.update_alert_status(row["id"], "dismissed", note or None, SystemClock().now_iso()); st.rerun()


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
    st.markdown(content)
    st.download_button("Descargar", content.encode("utf-8"), chosen.name, "text/markdown")


def chat():
    st.title("Chat")
    prompt = st.chat_input("Pregunta sobre alertas, accesos, conexiones, archivos o persistencia")
    if prompt:
        from bootstrap import build_chat_service
        with st.chat_message("user"): st.write(prompt)
        try:
            result = build_chat_service().ask(prompt)
            with st.chat_message("assistant"):
                st.write(result["answer"])
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
