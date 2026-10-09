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


def _ollama_install_panel(settings):
    from application.ollama_install import install_command, start_install, verify_installation, winget_path

    st.subheader("Instalar Ollama", divider="gray")
    winget = winget_path()
    if not winget:
        st.warning("winget no está disponible. Use la descarga oficial de Ollama.")
        st.link_button("Abrir descarga oficial", "https://ollama.com/download/windows",
                       icon=":material/open_in_new:")
        return
    command = " ".join(install_command(winget))
    st.code(command, language="powershell")
    confirmed = st.checkbox("Confirmo que deseo instalar Ollama y aceptar los acuerdos mostrados por winget.",
                            key="ollama-install-confirm")
    if st.button("Instalar Ollama", disabled=not confirmed, icon=":material/download:", key="ollama-install"):
        try:
            child = start_install()
            st.session_state["ollama-install-pid"] = child.pid
            st.info(f"Instalación iniciada en una consola visible (PID {child.pid}). Al terminar, pulse Verificar.")
        except Exception as exc:
            st.error(f"No se pudo iniciar winget: {type(exc).__name__}: {exc}")
    if st.button("Verificar instalación", icon=":material/fact_check:", key="ollama-verify"):
        result = verify_installation()
        if not result["installed"]:
            st.error(result["error"])
        elif not result["signature_valid"]:
            st.error(f"Ollama fue encontrado, pero su firma no es válida ({result.get('signature_status')}).")
        else:
            st.success(f"Ejecutable firmado · {result.get('version') or 'versión no disponible'}")
            st.caption(f"Publicador: {result.get('publisher') or 'no informado'} · Ruta: {result['path']}")
            if result["api"]:
                st.success(f"API local disponible · versión {result.get('api_version')}")
            else:
                st.warning("La API local todavía no responde. Abra Ollama desde Inicio y vuelva a verificar.")

    if ollama_installed():
        st.markdown("**Descarga opcional de modelos**")
        model = st.selectbox("Modelo", ["qwen3.5:4b", "qwen3.5:0.8b", "embeddinggemma:latest"],
                             key="ollama-pull-model")
        pull_confirmed = st.checkbox(f"Confirmo la descarga de `{model}` desde el registro de Ollama.",
                                     key="ollama-pull-confirm")
        if st.button("Descargar modelo", disabled=not pull_confirmed, icon=":material/cloud_download:",
                     key="ollama-pull"):
            from infrastructure.ollama.client import pull_model
            progress = st.progress(0, text="Iniciando descarga…")
            try:
                for status, completed, total in pull_model(settings, model):
                    value = min(completed / total, 1.0) if total else 0
                    progress.progress(value, text=status or "Descargando…")
                progress.progress(1.0, text="Modelo descargado")
                st.success(f"{model} está disponible.")
            except Exception as exc:
                st.error(f"No se pudo descargar el modelo: {type(exc).__name__}: {exc}")


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
        if not ollama_installed():
            _ollama_install_panel(settings)
        else:
            with st.expander("Instalación y modelos de Ollama", icon=":material/download:"):
                _ollama_install_panel(settings)

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
