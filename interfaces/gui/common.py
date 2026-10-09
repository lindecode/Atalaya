from __future__ import annotations

import streamlit as st

from infrastructure.sqlite.queries import SQLiteQueryRepository, since_hours
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


QUERY_TTL_SECONDS = 60
WINDOW_HOURS = {"1 hora": 1, "24 horas": 24, "7 días": 168, "30 días": 720}


def selected_window_hours() -> int:
    return WINDOW_HOURS.get(st.session_state.get("window"), 24)


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
    roles = {role: service.current(role) for role in ("analysis", "chat", "summary")}
    roles["embedding"] = settings.ollama_embedding_model
    try:
        available = {item["name"]: item for item in service.available()}
    except Exception as exc:  # Ollama down or unreachable: the rest of the GUI still works
        return {"provider": provider, "ready": False, "roles": roles, "error": f"{type(exc).__name__}: {exc}",
                "chat_tools": None}
    chat = available.get(roles["chat"])
    return {"provider": provider, "ready": chat is not None, "roles": roles, "chat_tools": chat["tools"] if chat else None,
            "error": None if chat else f"{roles['chat']} no está descargado"}


def refresh_ai_status() -> None:
    ai_status.clear()


def _ai_badge():
    """Sidebar: which model answers and whether it is ready; choosing happens only in IA local."""
    status = ai_status()
    names = {"ollama": "Ollama", "llama_cpp": "llama.cpp", "none": "Sin IA"}
    if status["provider"] == "none":
        line = ":gray[●] Sin IA: solo reglas y alertas"
    elif status["ready"]:
        line = f":green[●] {status['roles'].get('chat')} · {names.get(status['provider'], status['provider'])}"
    else:
        line = f":orange[●] {names.get(status['provider'], status['provider'])} no disponible"
    st.sidebar.markdown("**IA local**")
    st.sidebar.caption(line)
    try:
        st.sidebar.page_link(AI_PAGE, label="Configurar IA local", icon=":material/tune:")
    except Exception:  # a page run on its own (tests) has no navigation to link to
        pass


def _actions(settings):
    """Collect / analyze buttons, available from every page."""
    from bootstrap import build_analyze_service, build_collect_service
    from infrastructure.windows.common import is_admin

    left, right = st.sidebar.columns(2)
    if left.button("Recolectar", width="stretch", icon=":material/radar:", key="action-collect"):
        with st.sidebar.status("Recolectando...") as status:
            result = build_collect_service(settings).execute()
            status.update(label=f"Recolección {result['status']}", state="complete")
        st.cache_data.clear()
    if right.button("Analizar", width="stretch", icon=":material/psychology:", key="action-analyze"):
        with st.sidebar.status("Analizando...") as status:
            result = build_analyze_service(settings).execute()
            status.update(label=f"Análisis {result['status']}", state="complete")
        st.cache_data.clear()
    if not is_admin():
        st.sidebar.caption(":material/info: Sin administrador: algunas fuentes pueden omitirse (ver Estado).")


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
    options = WINDOW_HOURS
    label = st.sidebar.selectbox("Ventana temporal", list(options), index=1, key="window", disabled=not window_applies,
                                 help="Periodo que muestran las páginas de evidencia, alertas e historial."
                                 if window_applies else "Esta página no depende de la ventana temporal.")
    _actions(settings)
    st.sidebar.divider()
    _ai_badge()
    st.sidebar.divider()
    st.sidebar.caption(":material/notifications_active: Atalaya sigue en segundo plano aunque cierre esta ventana. "
                       "Para salir: icono junto al reloj > Salir de Atalaya.")
    if st.sidebar.button("Acerca de", icon=":material/info:", width="stretch", key="action-about"):
        about_dialog()
    return settings, repository, query, since_hours(options[label])
