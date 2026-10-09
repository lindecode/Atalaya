from __future__ import annotations

import streamlit as st

from infrastructure.logging_config import configure_logging
from shared.about import DISPLAY_NAME, ICON_PATH


configure_logging("gui")

st.set_page_config(page_title=DISPLAY_NAME, page_icon=str(ICON_PATH) if ICON_PATH.exists() else "🛡️",
                   layout="wide", initial_sidebar_state="expanded")

# Each page script is standalone (tests run them directly); this file only groups them into sections.
# The scripts live in views/, not pages/: Streamlit would otherwise also build its automatic file menu.
# Every page has a fixed url_path so links (tray menu, bookmarks, ?id=/?q= deep links) stay stable.
navigation = st.navigation({
    "Inicio": [
        st.Page("views/01_Panel.py", title="Panel", icon=":material/dashboard:", default=True),
        st.Page("views/02_En_vivo.py", title="En vivo", icon=":material/pulse_alert:", url_path="en-vivo"),
        st.Page("views/03_Alertas.py", title="Alertas", icon=":material/notification_important:", url_path="alertas"),
    ],
    "Investigar": [
        st.Page("views/10_Buscar.py", title="Buscar", icon=":material/search:", url_path="buscar"),
        st.Page("views/11_Conexiones.py", title="Conexiones", icon=":material/hub:", url_path="conexiones"),
        st.Page("views/12_Procesos.py", title="Procesos y RAM", icon=":material/memory:", url_path="procesos"),
        st.Page("views/13_Accesos.py", title="Accesos", icon=":material/key:", url_path="accesos"),
        st.Page("views/14_Archivos.py", title="Archivos", icon=":material/folder_open:", url_path="archivos"),
        st.Page("views/15_Persistencia.py", title="Persistencia", icon=":material/autorenew:", url_path="persistencia"),
        st.Page("views/16_Firewall.py", title="Firewall", icon=":material/security:", url_path="firewall"),
    ],
    "IA": [
        st.Page("views/20_Historial.py", title="Historial de análisis", icon=":material/history_edu:",
                url_path="historial"),
        st.Page("views/21_Chat.py", title="Chat", icon=":material/forum:", url_path="chat"),
        st.Page("views/22_Informes.py", title="Informes", icon=":material/description:", url_path="informes"),
    ],
    "Sistema": [
        st.Page("views/30_Primeros_pasos.py", title="Primeros pasos", icon=":material/rocket_launch:",
                url_path="primeros-pasos"),  # fixed URL: the tray menu links to it
        st.Page("views/31_IA_local.py", title="IA local", icon=":material/smart_toy:", url_path="ia-local"),
        st.Page("views/32_Ajustes.py", title="Ajustes", icon=":material/settings:", url_path="ajustes"),
    ],
}, expanded=True)
navigation.run()
