from __future__ import annotations

import streamlit as st

from bootstrap import build_automation_config_service
from infrastructure.logging_config import configure_logging
from infrastructure.sqlite.queries import SQLiteQueryRepository
from interfaces.gui.components import apply_style
from settings import Settings
from shared.about import DISPLAY_NAME, ICON_PATH
from shared.i18n import DEFAULT_LANGUAGE, t


configure_logging("gui")

st.set_page_config(page_title=DISPLAY_NAME, page_icon=str(ICON_PATH) if ICON_PATH.exists() else "🛡️",
                   layout="wide", initial_sidebar_state="expanded")
apply_style()

settings = Settings()
try:
    automation_cfg = build_automation_config_service(settings).load()
    lang = st.session_state.get("language") or automation_cfg.language or settings.language or DEFAULT_LANGUAGE
except Exception:
    lang = st.session_state.get("language") or settings.language or DEFAULT_LANGUAGE
st.session_state["language"] = lang


def _alerts_page_title(lang: str, settings: Settings) -> str:
    base = t("nav.pages.alerts", lang=lang)
    try:
        if not settings.database_path.exists():
            return base
        count = sum(SQLiteQueryRepository(settings).open_alerts_by_severity().values())
        if count <= 0:
            return base
        badge = "99+" if count > 99 else str(count)
        return f"{base} :red-badge[{badge}]"
    except Exception:
        return base


# Each page script is standalone (tests run them directly); this file only groups them into sections.
# The scripts live in views/, not pages/: Streamlit would otherwise also build its automatic file menu.
# Every page has a fixed url_path so links (tray menu, bookmarks, ?id=/?q= deep links) stay stable.
navigation = st.navigation({
    t("nav.sections.home", lang=lang): [
        st.Page("views/00_Guia.py", title="User guide" if lang == "en" else "Guía de Atalaya",
                icon=":material/menu_book:", url_path="guia"),
        st.Page("views/01_Panel.py", title=t("nav.pages.overview", lang=lang), icon=":material/dashboard:", default=True),
        st.Page("views/04_Desarrollo.py", title=t("nav.pages.development", lang=lang), icon=":material/terminal:",
                url_path="desarrollo"),
        st.Page("views/02_En_vivo.py", title=t("nav.pages.live", lang=lang), icon=":material/pulse_alert:", url_path="en-vivo"),
        st.Page("views/03_Alertas.py", title=_alerts_page_title(lang, settings), icon=":material/notification_important:", url_path="alertas"),
    ],
    t("nav.sections.investigate", lang=lang): [
        st.Page("views/10_Buscar.py", title=t("nav.pages.search", lang=lang), icon=":material/search:", url_path="buscar"),
        st.Page("views/11_Conexiones.py", title=t("nav.pages.connections", lang=lang), icon=":material/hub:", url_path="conexiones"),
        st.Page("views/12_Procesos.py", title=t("nav.pages.processes", lang=lang), icon=":material/memory:", url_path="procesos"),
        st.Page("views/13_Accesos.py", title=t("nav.pages.access", lang=lang), icon=":material/key:", url_path="accesos"),
        st.Page("views/14_Archivos.py", title=t("nav.pages.files", lang=lang), icon=":material/folder_open:", url_path="archivos"),
        st.Page("views/15_Persistencia.py", title=t("nav.pages.persistence", lang=lang), icon=":material/autorenew:", url_path="persistencia"),
        st.Page("views/16_Firewall.py", title=t("nav.pages.firewall", lang=lang), icon=":material/security:", url_path="firewall"),
    ],
    t("nav.sections.ai", lang=lang): [
        st.Page("views/20_Historial.py", title=t("nav.pages.history", lang=lang), icon=":material/history_edu:",
                url_path="historial"),
        st.Page("views/21_Chat.py", title=t("nav.pages.chat", lang=lang), icon=":material/forum:", url_path="chat"),
        st.Page("views/22_Informes.py", title=t("nav.pages.reports", lang=lang), icon=":material/description:", url_path="informes"),
    ],
    t("nav.sections.system", lang=lang): [
        st.Page("views/30_Primeros_pasos.py", title=t("nav.pages.getting_started", lang=lang), icon=":material/rocket_launch:",
                url_path="primeros-pasos"),  # fixed URL: the tray menu links to it
        st.Page("views/31_IA_local.py", title=t("nav.pages.local_ai", lang=lang), icon=":material/smart_toy:", url_path="ia-local"),
        st.Page("views/32_Ajustes.py", title=t("nav.pages.settings", lang=lang), icon=":material/settings:", url_path="ajustes"),
    ],
}, expanded=True)
navigation.run()
