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
    st.sidebar.subheader("LLM local")
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

    chosen = st.sidebar.selectbox("Modelo para analizar y chat", names, index=names.index(current) if current in by_name else 0,
                                  format_func=label, key="llm_model")
    if chosen != current:
        service.select(chosen)
        st.sidebar.success(f"Modelo guardado: {chosen}")
    if not by_name[chosen]["tools"]:
        st.sidebar.caption("Este modelo no admite tool calling: sirve para Analizar, no para el Chat.")
    return by_name[chosen]


def context():
    settings = Settings()
    repository = SQLiteRepository(settings)
    repository.initialize()
    query = SQLiteQueryRepository(settings)
    options = {"1 hora": 1, "24 horas": 24, "7 días": 168, "30 días": 720}
    label = st.sidebar.selectbox("Ventana temporal", list(options), index=1)
    st.sidebar.caption("Servidor local: 127.0.0.1")
    model_selector()
    return settings, repository, query, since_hours(options[label])
