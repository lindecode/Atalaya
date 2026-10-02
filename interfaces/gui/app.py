from __future__ import annotations

import streamlit as st

from shared.about import ICON_PATH


st.set_page_config(page_title="Atalaya", page_icon=str(ICON_PATH) if ICON_PATH.exists() else "🛡️",
                   layout="wide", initial_sidebar_state="expanded")

# Each page script is standalone (tests run them directly); this file only groups them into sections
navigation = st.navigation({
    "Vigilancia": [
        st.Page("pages/0_Panel.py", title="Panel", icon=":material/dashboard:", default=True),
        st.Page("pages/3_Conexiones.py", title="Conexiones", icon=":material/hub:"),
        st.Page("pages/2_Alertas.py", title="Alertas", icon=":material/notification_important:"),
        st.Page("pages/1_Resumen.py", title="Actividad", icon=":material/monitoring:"),
    ],
    "Evidencia": [
        st.Page("pages/4_Accesos.py", title="Accesos", icon=":material/key:"),
        st.Page("pages/5_Archivos.py", title="Archivos", icon=":material/folder_open:"),
        st.Page("pages/6_Persistencia.py", title="Persistencia", icon=":material/autorenew:"),
        st.Page("pages/7_Firewall.py", title="Firewall", icon=":material/security:"),
    ],
    "Herramientas": [
        st.Page("pages/11_Primeros_pasos.py", title="Primeros pasos", icon=":material/rocket_launch:"),
        st.Page("pages/9_Chat.py", title="Chat", icon=":material/forum:"),
        st.Page("pages/8_Informes.py", title="Informes", icon=":material/description:"),
        st.Page("pages/10_Estado.py", title="Estado", icon=":material/settings:"),
    ],
})
navigation.run()
