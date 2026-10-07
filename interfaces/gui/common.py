from __future__ import annotations

import streamlit as st

from infrastructure.sqlite.queries import SQLiteQueryRepository, since_hours
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


@st.cache_data(ttl=60, show_spinner=False)
def _installed_models() -> tuple[list[dict], str | None]:
    from bootstrap import build_model_service
    try:
        return build_model_service().available(), None
    except Exception as exc:  # Ollama down or unreachable: the rest of the GUI still works
        return [], f"{type(exc).__name__}: {exc}"


def model_selector() -> dict | None:
    """Sidebar picker for the local LLM; the choice is stored in SQLite and used by analyze and chat."""
    from bootstrap import build_model_service
    service = build_model_service()
    current = service.current()
    models, error = _installed_models()
    st.sidebar.markdown("**LLM local**")
    if error:
        st.sidebar.error(f"Ollama no disponible. Modelo configurado: {current}")
        return None
    usable = [model for model in models if model["chat"]]
    if not usable:
        st.sidebar.warning("No hay modelos de chat en Ollama. Ejemplo: ollama pull qwen3.5:4b")
        return None
    names = [model["name"] for model in usable]
    by_name = {model["name"]: model for model in usable}
    if current not in by_name:
        st.sidebar.warning(f"{current} no está instalado; elija otro.")

    def label(name: str) -> str:
        model = by_name[name]
        return f"{name} · {model['parameters'] or '?'} · {model['size_gb']} GB" + ("" if model["tools"] else " · sin tools")

    chosen = st.sidebar.selectbox("Modelo para chat", names, index=names.index(current) if current in by_name else 0,
                                  format_func=label, key="llm_model")
    if chosen != current:
        service.select(chosen)
        st.sidebar.success(f"Modelo guardado: {chosen}")
    if not by_name[chosen]["tools"]:
        st.sidebar.caption("Este modelo no admite tool calling: sirve para Analizar, no para el Chat.")
    st.session_state["llm_model_info"] = by_name[chosen]
    return by_name[chosen]


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


def context():
    from interfaces.gui.components import about_dialog, apply_style
    from shared.about import ICON_PATH, WORDMARK_PATHS

    apply_style()
    settings = Settings()
    repository = SQLiteRepository(settings)
    repository.initialize()
    query = SQLiteQueryRepository(settings)
    # Name and subtitle sit beside the icon in the sidebar header; collapsed, only the icon remains
    wordmark = WORDMARK_PATHS["light" if getattr(st.context.theme, "type", None) == "light" else "dark"]
    if wordmark.exists() and ICON_PATH.exists():
        st.logo(str(wordmark), icon_image=str(ICON_PATH), size="large")
    elif ICON_PATH.exists():
        st.logo(str(ICON_PATH), size="large")
    options = {"1 hora": 1, "24 horas": 24, "7 días": 168, "30 días": 720}
    label = st.sidebar.selectbox("Ventana temporal", list(options), index=1, key="window")
    _actions(settings)
    st.sidebar.divider()
    model_selector()
    st.sidebar.divider()
    st.sidebar.caption(":material/notifications_active: Atalaya sigue en segundo plano aunque cierre esta ventana. "
                       "Para salir: icono junto al reloj > Salir de Atalaya.")
    if st.sidebar.button("Acerca de", icon=":material/info:", width="stretch", key="action-about"):
        about_dialog()
    return settings, repository, query, since_hours(options[label])
