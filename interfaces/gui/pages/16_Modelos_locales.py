from __future__ import annotations

from pathlib import Path

import pandas as pd
import psutil
import streamlit as st

from infrastructure.ai_registry import ModelRegistry, ROLES, hardware_recommendations
from infrastructure.llm_provider import effective_settings, ollama_installed, provider_name
from interfaces.gui.common import context
from interfaces.gui.components import hero


ROLE_NAMES = {"chat": "Chat con herramientas", "analysis": "Análisis", "summary": "Resúmenes",
              "embedding": "Embeddings"}


def main():
    settings, _, _, _ = context()
    registry = ModelRegistry()
    hero("🧠 Modelos locales", "Autorice modelos GGUF y elija su función. Atalaya no escanea ni descarga archivos.")

    current_provider = registry.provider()
    provider = st.selectbox("Proveedor", ["auto", "llama_cpp", "ollama", "none"],
                            index=["auto", "llama_cpp", "ollama", "none"].index(current_provider),
                            format_func=lambda value: {"auto": "Automático", "llama_cpp": "llama.cpp portable",
                                                       "ollama": "Ollama", "none": "Sin IA"}[value])
    if provider != current_provider:
        registry.set_provider(provider)
        st.success("Proveedor guardado. Se aplicará en la siguiente operación de IA.")
    selected = provider_name(settings)
    st.info(f"Proveedor efectivo: **{selected}**" +
            (". Reglas, recolección y alertas siguen activas." if selected == "none" else ""))
    if provider in {"auto", "ollama"}:
        st.caption("Ollama detectado en el equipo." if ollama_installed() else "Ollama no está instalado.")

    st.subheader("Runtime llama.cpp autorizado", divider="gray")
    runtime = registry.runtime()
    runtime_path = st.text_input("Ruta de llama-server.exe", value=(runtime or {}).get("path", ""),
                                 placeholder=r"C:\IA\llama.cpp\llama-server.exe")
    if st.button("Autorizar runtime", disabled=not runtime_path, icon=":material/verified_user:"):
        try:
            saved = registry.register_runtime(Path(runtime_path))
            st.success(f"Runtime autorizado · SHA-256 {saved['sha256'][:16]}…")
        except (OSError, ValueError) as exc:
            st.error(str(exc))

    st.subheader("Registrar un GGUF", divider="gray")
    with st.form("register-gguf"):
        path = st.text_input("Ruta del archivo", placeholder=r"D:\Modelos\modelo.gguf")
        roles = st.multiselect("Funciones autorizadas", list(ROLES), format_func=ROLE_NAMES.get)
        submitted = st.form_submit_button("Validar y registrar", icon=":material/add:")
    if submitted:
        try:
            model = registry.register(Path(path), tuple(roles))
            st.success(f"{model.name} registrado · {model.size_bytes / 1024**3:.1f} GB · SHA-256 {model.sha256[:16]}…")
        except (OSError, ValueError) as exc:
            st.error(str(exc))

    models = registry.models()
    if models:
        st.subheader("Modelos autorizados", divider="gray")
        st.dataframe(pd.DataFrame([{"Modelo": m.name, "Ruta": m.path, "GB": round(m.size_bytes / 1024**3, 2),
                                    "GGUF": m.gguf_version, "Funciones": ", ".join(ROLE_NAMES[r] for r in m.roles),
                                    "SHA-256": m.sha256} for m in models]), hide_index=True, width="stretch")
        recommendations = hardware_recommendations(models, psutil.virtual_memory().total)
        st.caption(f"Recomendaciones conservadoras para {psutil.virtual_memory().total / 1024**3:.0f} GB de RAM; "
                   "no se aplican automáticamente.")
        by_id = {model.id: model for model in models}
        for role in ROLES:
            eligible = [model for model in models if role in model.roles]
            if not eligible:
                continue
            current = registry.assigned(role)
            choice = st.selectbox(ROLE_NAMES[role], [model.id for model in eligible],
                                  index=next((i for i, model in enumerate(eligible) if current and model.id == current.id), 0),
                                  format_func=lambda model_id: by_id[model_id].name, key=f"registry-{role}")
            recommended = recommendations.get(role)
            st.caption("Recomendado: " + (by_id[recommended].name if recommended in by_id else "ninguno cabe con margen seguro"))
            if st.button(f"Asignar a {ROLE_NAMES[role]}", key=f"assign-{role}"):
                registry.assign(role, choice)
                st.success("Asignación guardada.")

    st.subheader("Prueba controlada", divider="gray")
    st.caption("Solo se ejecuta al pulsar el botón. Verifica que el proveedor pueda iniciar y listar el modelo.")
    if st.button("Probar configuración", icon=":material/play_arrow:"):
        try:
            from bootstrap import build_model_service
            available = build_model_service(effective_settings(settings)).available()
            st.success(f"Proveedor operativo · {len(available)} modelo(s) disponible(s).")
        except Exception as exc:
            st.error(f"La prueba falló: {type(exc).__name__}: {exc}")


main()
