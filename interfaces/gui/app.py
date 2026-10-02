from __future__ import annotations

import streamlit as st

from bootstrap import build_analyze_service, build_collect_service
from infrastructure.windows.common import is_admin
from interfaces.gui.common import context


st.set_page_config(page_title="network-llm", page_icon="🛡️", layout="wide")
st.title("🛡️ network-llm")
st.caption("Visibilidad local y de solo lectura para este equipo Windows")
settings, repository, query, since = context()

left, right = st.sidebar.columns(2)
if left.button("Recolectar", use_container_width=True):
    with st.status("Recolectando...") as status:
        result = build_collect_service(settings).execute()
        status.update(label=f"Recolección {result['status']}", state="complete")
    st.cache_data.clear()
if right.button("Analizar", use_container_width=True):
    with st.status("Analizando...") as status:
        result = build_analyze_service(settings).execute()
        status.update(label=f"Análisis {result['status']}", state="complete")
    st.cache_data.clear()
if not is_admin():
    st.sidebar.warning("Sin administrador: Security y algunos metadatos pueden omitirse.")

counts = query.counts(since)
columns = st.columns(5)
for column, (label, value) in zip(columns, (("Alertas", counts["alerts"]), ("Accesos", counts["auth_events"]),
                                                   ("Conexiones", counts["connections"]), ("Archivos", counts["file_events"]),
                                                   ("Persistencia", counts["persistence_items"]))):
    column.metric(label, value)

analysis = query.latest_analysis()
if analysis and analysis.get("result_json"):
    st.subheader("Último análisis")
    st.text(analysis["result_json"]["summary"])
    st.metric("Riesgo global", analysis["result_json"]["overall_risk"].upper())
else:
    st.info("Todavía no hay un análisis LLM válido. Las alertas por reglas siguen disponibles.")

