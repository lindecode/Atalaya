"""'IA local': the one place to choose the provider and the model of each role, install Ollama and register GGUFs."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import psutil
import streamlit as st

from application.model_advisor import (CATALOG_VERSION, OLLAMA_CATALOG, detect_hardware, enough_disk,
                                       functional_test, recommendation)
from infrastructure.ai_registry import ModelRegistry, ROLES, hardware_recommendations
from infrastructure.llm_provider import effective_settings, ollama_installed, provider_name
from interfaces.gui.common import ai_status, context, refresh_ai_status
from interfaces.gui.components import hero, plain_label


ROLE_NAMES = {"chat": "Chat con herramientas", "analysis": "Análisis de alertas", "summary": "Resúmenes",
              "embedding": "Embeddings"}
PROVIDER_NAMES = {"auto": "Automático", "llama_cpp": "llama.cpp portable", "ollama": "Ollama", "none": "Sin IA"}


@st.cache_data(ttl=300, show_spinner=False)
def _hardware():
    return detect_hardware()


def _ollama_recommendations():
    hardware = _hardware()
    advised = recommendation(hardware)
    a, b, c, d = st.columns(4)
    a.metric("RAM", f"{hardware['ram_gb']:.0f} GB")
    b.metric("VRAM NVIDIA", f"{hardware['vram_gb']:.0f} GB" if hardware["vram_gb"] else "No detectada")
    c.metric("CPU", f"{hardware['cpu_threads']} hilos")
    d.metric("Disco libre", f"{hardware['disk_free_gb']:.0f} GB")
    st.info(f"Recomendación Atalaya (catálogo v{CATALOG_VERSION}): **{advised['analysis']}** para chat/análisis, "
            f"**{advised['summary']}** para resúmenes y **{advised['embedding']}** para RAG. {advised['reason']}")
    if not advised["fits_disk"]:
        st.error(f"El conjunto necesita aproximadamente {advised['required_disk_gb']:.1f} GB con margen y no cabe "
                 "en el espacio libre actual.")
    return hardware, advised


def _status_header(settings):
    """What is in use right now, before any setting."""
    status = ai_status()
    with st.container(border=True):
        st.markdown(f"**En uso** · proveedor {PROVIDER_NAMES.get(status['provider'], status['provider'])}"
                    + (" · listo" if status["ready"] else ""))
        if status["provider"] == "none":
            st.caption("Sin IA: recolección, reglas y alertas siguen activas; no hay explicaciones, chat ni resúmenes.")
            return
        columns = st.columns(len(status["roles"]))
        for column, (role, model) in zip(columns, status["roles"].items()):
            column.metric(ROLE_NAMES[role], model or "—")
        if not status["ready"]:
            st.warning(f"El proveedor no responde: {status['error']}", icon=":material/cloud_off:")


def _ollama_roles(settings):
    from bootstrap import build_model_service

    model_service = build_model_service(settings)
    try:
        installed = model_service.available()
    except Exception as exc:
        st.warning(f"Ollama no disponible: {exc}. Instálelo o arránquelo en la pestaña Ollama.")
        return
    usable = [item for item in installed if item["chat"]]
    names = [item["name"] for item in usable]
    if not names:
        st.info("No hay modelos de chat descargados. Descargue uno en la pestaña Ollama.")
        return
    by_name = {item["name"]: item for item in usable}
    recommendations = model_service.recommendations()
    columns = st.columns(3)
    for column, role in zip(columns, ("analysis", "chat", "summary")):
        current = model_service.current(role)
        selected = column.selectbox(ROLE_NAMES[role], names, index=names.index(current) if current in names else 0,
                                    key=f"model-role-{role}",
                                    format_func=lambda name: f"{name} · {by_name[name]['parameters'] or '?'}"
                                                             + ("" if by_name[name]["tools"] else " · sin tools"))
        recommended = recommendations.get(role)
        column.caption("Recomendado en este equipo: " + (recommended["name"] if recommended else "ninguno"))
        if role == "chat" and not by_name[selected]["tools"]:
            column.warning("Este modelo no admite herramientas: el chat no podrá consultar la evidencia.")
        if selected != current:
            model_service.select(selected, role)
            refresh_ai_status()
            column.success("Guardado")
    embedding = recommendations.get("embedding")
    st.caption(f"Embeddings: `{settings.ollama_embedding_model}`"
               + (f" · recomendado `{embedding['name']}`" if embedding else "")
               + ". Las recomendaciones usan capacidades y tamaño instalados; valide con los evals locales.")


def _registry_roles(registry: ModelRegistry):
    models = registry.models()
    if not models:
        st.info("No hay modelos GGUF autorizados. Regístrelos en la pestaña llama.cpp.")
        return
    recommendations = hardware_recommendations(models, psutil.virtual_memory().total)
    st.caption(f"Recomendaciones conservadoras para {psutil.virtual_memory().total / 1024**3:.0f} GB de RAM; "
               "no se aplican automáticamente.")
    by_id = {model.id: model for model in models}
    for role in ROLES:
        eligible = [model for model in models if role in model.roles]
        if not eligible:
            continue
        current = registry.assigned(role)
        left, right = st.columns([3, 1], vertical_alignment="bottom")
        choice = left.selectbox(ROLE_NAMES[role], [model.id for model in eligible],
                                index=next((i for i, model in enumerate(eligible) if current and model.id == current.id), 0),
                                format_func=lambda model_id: by_id[model_id].name, key=f"registry-{role}")
        recommended = recommendations.get(role)
        left.caption("Recomendado: " + (by_id[recommended].name if recommended in by_id else "ninguno cabe con margen seguro"))
        if right.button("Asignar", key=f"assign-{role}", width="stretch"):
            registry.assign(role, choice)
            refresh_ai_status()
            st.success(f"{by_id[choice].name} asignado a {ROLE_NAMES[role]}.")


def _ollama_install_panel(settings):
    from application.ollama_install import install_command, start_install, verify_installation, winget_path

    if ollama_installed():
        st.success("Ollama está instalado en este equipo.", icon=":material/check_circle:")
    winget = winget_path()
    with st.expander("Instalar o verificar Ollama", icon=":material/install_desktop:", expanded=not ollama_installed()):
        if not winget:
            st.warning("winget no está disponible. Use la descarga oficial de Ollama.")
            st.link_button("Abrir descarga oficial", "https://ollama.com/download/windows",
                           icon=":material/open_in_new:")
        else:
            st.code(" ".join(install_command(winget)), language="powershell")
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
                refresh_ai_status()

    if ollama_installed():
        st.markdown("**Recomendación y descarga de modelos**")
        hardware, advised = _ollama_recommendations()
        catalog = {spec.name: spec for spec in OLLAMA_CATALOG}
        names = list(catalog)
        model = st.selectbox("Modelo revisado", names, key="ollama-pull-model",
                             index=names.index(advised["analysis"]),
                             format_func=lambda name: f"{catalog[name].label} · {catalog[name].size_gb:.1f} GB · "
                                                      + ", ".join(ROLE_NAMES[role] for role in catalog[name].roles))
        spec = catalog[model]
        fits, required = enough_disk(model, hardware)
        st.caption(f"Descarga aproximada: {spec.size_gb:.1f} GB · espacio requerido con margen: {required:.1f} GB · "
                   f"RAM mínima orientativa: {spec.min_ram_gb:.0f} GB. La recomendación no instala nada por sí sola.")
        if hardware["ram_gb"] < spec.min_ram_gb:
            st.warning("Este modelo supera la RAM mínima orientativa del equipo y puede ser muy lento o no cargar.")
        if not fits:
            st.error("No hay espacio libre suficiente con el margen de seguridad del 20 %.")
        pull_confirmed = st.checkbox(f"Confirmo la descarga de `{model}` desde el registro de Ollama.",
                                     key="ollama-pull-confirm")
        if st.button("Descargar y validar", disabled=not pull_confirmed or not fits, icon=":material/cloud_download:",
                     key="ollama-pull"):
            from infrastructure.ollama.client import pull_model
            progress = st.progress(0, text="Iniciando descarga…")
            try:
                for status, completed, total in pull_model(settings, model):
                    value = min(completed / total, 1.0) if total else 0
                    progress.progress(value, text=status or "Descargando…")
                progress.progress(1.0, text="Modelo descargado")
                result = functional_test(settings, model)
                refresh_ai_status()
                detail = (f"{result.get('dimensions')} dimensiones" if result["test"] == "embedding"
                          else "chat, JSON estructurado y capacidad de herramientas")
                st.success(f"{model} está disponible y superó la prueba: {detail}.")
            except Exception as exc:
                st.error(f"La descarga o validación falló: {type(exc).__name__}: {exc}")


def _llama_cpp_panel(registry: ModelRegistry):
    st.markdown("**Runtime llama.cpp autorizado**")
    runtime = registry.runtime()
    runtime_path = st.text_input("Ruta de llama-server.exe", value=(runtime or {}).get("path", ""),
                                 placeholder=r"C:\IA\llama.cpp\llama-server.exe")
    if st.button("Autorizar runtime", disabled=not runtime_path, icon=":material/verified_user:"):
        try:
            saved = registry.register_runtime(Path(runtime_path))
            st.success(f"Runtime autorizado · SHA-256 {saved['sha256'][:16]}…")
        except (OSError, ValueError) as exc:
            st.error(str(exc))

    st.markdown("**Registrar un GGUF**")
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
        st.markdown("**Modelos autorizados**")
        st.dataframe(pd.DataFrame([{"Modelo": m.name, "Ruta": m.path, "GB": round(m.size_bytes / 1024**3, 2),
                                    "GGUF": m.gguf_version, "Funciones": ", ".join(ROLE_NAMES[r] for r in m.roles),
                                    "SHA-256": m.sha256} for m in models]), hide_index=True, width="stretch")
        st.caption("La función que usa cada modelo se elige en la pestaña «Modelos por función».")


def local_ai():
    settings, _, _, _ = context(window_applies=False)
    registry = ModelRegistry()
    hero("🤖 IA local", "Proveedor, modelo de cada función, instalación de Ollama y modelos GGUF. Atalaya no descarga "
                       "ni instala nada sin su confirmación.")
    _status_header(settings)

    current_provider = registry.provider()
    options = list(PROVIDER_NAMES)
    provider = st.selectbox("Proveedor", options, index=options.index(current_provider), format_func=PROVIDER_NAMES.get,
                            help="Automático usa llama.cpp si hay un runtime y un modelo autorizados; si no, Ollama.")
    if provider != current_provider:
        registry.set_provider(provider)
        refresh_ai_status()
        st.success("Proveedor guardado. Se aplicará en la siguiente operación de IA.")
    selected = provider_name(settings)

    roles_tab, ollama_tab, llama_tab, test_tab = st.tabs([":material/tune: Modelos por función", ":material/download: Ollama",
                                                          ":material/memory_alt: llama.cpp", ":material/play_arrow: Prueba"])
    with roles_tab:
        if selected == "none":
            st.info("Sin IA seleccionada: no hay modelos que asignar.")
        elif selected == "llama_cpp":
            _registry_roles(registry)
        else:
            _ollama_roles(settings)
    with ollama_tab:
        _ollama_install_panel(settings)
    with llama_tab:
        _llama_cpp_panel(registry)
    with test_tab:
        st.caption("Solo se ejecuta al pulsar el botón. Verifica que el proveedor pueda iniciar y listar sus modelos.")
        if st.button("Probar configuración", icon=":material/play_arrow:"):
            try:
                from bootstrap import build_model_service
                available = build_model_service(effective_settings(settings)).available()
                refresh_ai_status()
                st.success(f"Proveedor operativo · {len(available)} modelo(s) disponible(s): "
                           + plain_label(", ".join(item["name"] for item in available[:8])))
            except Exception as exc:
                st.error(f"La prueba falló: {type(exc).__name__}: {exc}")
