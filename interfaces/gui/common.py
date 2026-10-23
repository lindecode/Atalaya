# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import streamlit as st

from infrastructure.sqlite.queries import SQLiteQueryRepository, since_hours
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings
from shared.i18n import t, DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES


QUERY_TTL_SECONDS = 60
WINDOW_HOURS = {"1 hora": 1, "24 horas": 24, "3 días": 72, "7 días": 168, "30 días": 720}


def selected_window_hours() -> int:
    return WINDOW_HOURS.get(st.session_state.get("window"), 24)


def get_ui_lang() -> str:
    """Current active language in Streamlit session_state, falling back to ATALAYA_LANG or default."""
    return st.session_state.get("language") or Settings().language or DEFAULT_LANGUAGE


@st.cache_data(ttl=QUERY_TTL_SECONDS, show_spinner=False)
def _cached_query(_query: SQLiteQueryRepository, database: str, method: str, args: tuple, kwargs: tuple):
    """One SQLite read per (database, method, arguments) per minute instead of one per widget interaction."""
    return getattr(_query, method)(*args, **dict(kwargs))


class CachedQueries:
    """Read-only facade over SQLiteQueryRepository whose results are cached; writes go through the repository."""

    def __init__(self, query: SQLiteQueryRepository):
        self._query = query

    def __getattr__(self, name):
        attribute = getattr(self._query, name)
        if not callable(attribute) or name.startswith("_"):
            return attribute
        # Live views have their own small, indexed queries and must not inherit the one-minute cache.
        if name.startswith("live_"):
            return attribute
        database = str(self._query.settings.database_path)
        return lambda *args, **kwargs: _cached_query(self._query, database, name, args, tuple(sorted(kwargs.items())))


def refresh_data() -> None:
    """Forget cached reads after collecting, analysing or changing alerts/baseline."""
    _cached_query.clear()


AI_PAGE = "views/31_IA_local.py"


@st.cache_data(ttl=60, show_spinner=False)
def ai_status() -> dict:
    """Provider in use, the model of each role and whether it answers; feeds the sidebar badge and IA local.

    With llama.cpp only the registry is read: probing it could start llama-server every minute.
    """
    from bootstrap import build_model_service
    from infrastructure.ai_registry import ModelRegistry
    from infrastructure.llm_provider import provider_name

    settings = Settings()
    try:
        provider = provider_name(settings)
    except Exception as exc:
        return {"provider": "?", "ready": False, "roles": {}, "error": f"{type(exc).__name__}: {exc}", "chat_tools": None}
    if provider == "none":
        return {"provider": "none", "ready": False, "roles": {}, "error": None, "chat_tools": None}
    if provider == "llama_cpp":
        registry = ModelRegistry()
        roles = {role: (registry.assigned(role).name if registry.assigned(role) else None)
                 for role in ("analysis", "chat", "summary", "embedding")}
        ready = bool(registry.runtime()) and bool(roles["chat"])
        return {"provider": provider, "ready": ready, "roles": roles, "chat_tools": None,
                "error": None if ready else "Falta autorizar el runtime o asignar el modelo de chat"}
    service = build_model_service(settings)
    roles = {role: service.current(role) for role in ("analysis", "chat", "summary", "embedding")}
    try:
        available = {item["name"]: item for item in service.available()}
    except Exception as exc:  # Ollama down or unreachable: the rest of the GUI still works
        return {"provider": provider, "ready": False, "roles": roles, "error": f"{type(exc).__name__}: {exc}",
                "chat_tools": None}

    def _find_model(target: str | None) -> dict | None:
        if not target:
            return None
        if target in available:
            return available[target]
        for alt in (f"{target}:latest", target.removesuffix(":latest")):
            if alt in available:
                return available[alt]
        target_f = target.casefold()
        for k, v in available.items():
            if k.casefold() == target_f or k.removesuffix(":latest").casefold() == target_f.removesuffix(":latest"):
                return v
        return None

    chat = _find_model(roles.get("chat"))
    return {"provider": provider, "ready": chat is not None, "roles": roles, "chat_tools": chat["tools"] if chat else None,
            "error": None if chat else f"{roles['chat']} no está descargado"}


def refresh_ai_status() -> None:
    ai_status.clear()


def _ai_badge(lang: str = DEFAULT_LANGUAGE):
    """Sidebar: which model answers and whether it is ready; choosing happens only in IA local."""
    status = ai_status()
    no_ai_name = "No AI" if lang == "en" else "Sin IA"
    names = {"ollama": "Ollama", "llama_cpp": "llama.cpp", "none": no_ai_name}
    if status["provider"] == "none":
        line = ":gray[●] No AI: deterministic rules only" if lang == "en" else ":gray[●] Sin IA: solo reglas y alertas"
    elif status["ready"]:
        line = f":green[●] {status['roles'].get('chat')} · {names.get(status['provider'], status['provider'])}"
    else:
        avail_msg = "unavailable" if lang == "en" else "no disponible"
        line = f":orange[●] {names.get(status['provider'], status['provider'])} {avail_msg}"
    st.sidebar.markdown("**Local AI**" if lang == "en" else "**IA local**")
    st.sidebar.caption(line)
    try:
        link_label = "Configure local AI" if lang == "en" else "Configurar IA local"
        st.sidebar.page_link(AI_PAGE, label=link_label, icon=":material/tune:")
    except Exception:  # a page run on its own (tests) has no navigation to link to
        pass


def _actions(settings, lang: str = DEFAULT_LANGUAGE):
    """Collect / analyze buttons, available from every page."""
    from bootstrap import build_analyze_service, build_collect_service
    from infrastructure.windows.common import is_admin

    btn_collect = t("common.collect", lang=lang, default="Recolectar")
    btn_analyze = "Analyze" if lang == "en" else "Analizar"
    left, right = st.sidebar.columns(2)
    if left.button(btn_collect, width="stretch", icon=":material/radar:", key="action-collect"):
        status_lbl = "Collecting..." if lang == "en" else "Recolectando..."
        with st.sidebar.status(status_lbl) as status:
            result = build_collect_service(settings).execute()
            done_lbl = f"Collection {result['status']}" if lang == "en" else f"Recolección {result['status']}"
            status.update(label=done_lbl, state="complete")
        st.cache_data.clear()
    if right.button(btn_analyze, width="stretch", icon=":material/psychology:", key="action-analyze"):
        status_lbl = "Analyzing..." if lang == "en" else "Analizando..."
        with st.sidebar.status(status_lbl) as status:
            result = build_analyze_service(settings).execute()
            done_lbl = f"Analysis {result['status']}" if lang == "en" else f"Análisis {result['status']}"
            status.update(label=done_lbl, state="complete")
        st.cache_data.clear()
    if not is_admin():
        admin_warning = (":material/info: Non-admin: some telemetry sources may be skipped (see Settings → Extended permissions)."
                         if lang == "en" else
                         ":material/info: Sin administrador: algunas fuentes pueden omitirse (ver Ajustes → Permisos ampliados).")
        st.sidebar.caption(admin_warning)


def context(window_applies: bool = True):
    """Shared page frame. `window_applies=False` greys out the sidebar window on pages that do not use it."""
    from interfaces.gui.components import about_dialog, apply_style
    from shared.about import ICON_PATH, WORDMARK_PATHS

    apply_style()
    settings = Settings()
    repository = SQLiteRepository(settings)
    repository.initialize()
    query = CachedQueries(SQLiteQueryRepository(settings))
    # Name and subtitle sit beside the icon in the sidebar header; collapsed, only the icon remains
    wordmark = WORDMARK_PATHS["light" if getattr(st.context.theme, "type", None) == "light" else "dark"]
    if wordmark.exists() and ICON_PATH.exists():
        st.logo(str(wordmark), icon_image=str(ICON_PATH), size="large")
    elif ICON_PATH.exists():
        st.logo(str(ICON_PATH), size="large")
    from bootstrap import build_automation_config_service
    automation_cfg = build_automation_config_service(settings).load()
    lang = st.session_state.get("language") or automation_cfg.language or settings.language or DEFAULT_LANGUAGE
    st.session_state["language"] = lang

    options = WINDOW_HOURS
    win_label = "Time window" if lang == "en" else "Ventana temporal"
    win_help = ("Time period displayed across evidence, alerts and history pages." if lang == "en" else
                "Periodo que muestran las páginas de evidencia, alertas e historial.") if window_applies else (
                "This page is independent of the time window." if lang == "en" else "Esta página no depende de la ventana temporal.")
    window_labels = {
        "1 hora": "1 hour" if lang == "en" else "1 hora",
        "24 horas": "24 hours" if lang == "en" else "24 horas",
        "3 días": "3 days" if lang == "en" else "3 días",
        "7 días": "7 days" if lang == "en" else "7 días",
        "30 días": "30 days" if lang == "en" else "30 días",
    }
    label = st.sidebar.selectbox(win_label, list(options), index=1, key="window", disabled=not window_applies, help=win_help,
                                 format_func=lambda opt: window_labels.get(opt, opt))
    _actions(settings, lang=lang)
    st.sidebar.divider()
    _ai_badge(lang=lang)
    st.sidebar.divider()
    tray_note = (":material/notifications_active: Atalaya keeps running in the background when you close this window. "
                 "To exit: tray icon > Exit Atalaya." if lang == "en" else
                 ":material/notifications_active: Atalaya sigue en segundo plano aunque cierre esta ventana. "
                 "Para salir: icono junto al reloj > Salir de Atalaya.")
    st.sidebar.caption(tray_note)
    about_label = "About" if lang == "en" else "Acerca de"
    if st.sidebar.button(about_label, icon=":material/info:", width="stretch", key="action-about"):
        about_dialog(lang=lang)
    return settings, repository, query, since_hours(options[label])
