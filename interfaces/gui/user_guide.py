"""In-app user manual: purpose, navigation, rules, privacy and terminology."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from application.rule_config import RULE_IDS
from bootstrap import build_rule_config_service
from domain.rules.help import RULES
from interfaces.gui.common import context
from interfaces.gui.components import hero, page_link
from shared.about import APP_VERSION, DISPLAY_NAME


SECTIONS = (
    ("Panel", "views/01_Panel.py", ":material/dashboard:",
     "Resumen de riesgo, alertas recientes y estado general."),
    ("En vivo", "views/02_En_vivo.py", ":material/pulse_alert:",
     "Estado de fuentes, ejecuciones recientes y actividad que llega al sistema."),
    ("Alertas", "views/03_Alertas.py", ":material/notification_important:",
     "Hallazgos de las reglas, evidencia, explicación y acciones de revisión."),
    ("Buscar", "views/10_Buscar.py", ":material/search:",
     "Búsqueda transversal de IP, usuario, proceso, ruta o hash."),
    ("Conexiones", "views/11_Conexiones.py", ":material/hub:",
     "Conexiones entrantes y salientes, puertos, servidores locales e IP observadas."),
    ("Procesos y RAM", "views/12_Procesos.py", ":material/memory:",
     "Consumo actual, crecimiento de memoria, rutas sospechosas e historial."),
    ("Accesos", "views/13_Accesos.py", ":material/key:",
     "Inicios de sesión, intentos fallidos, RDP y cambios de cuentas."),
    ("Archivos", "views/14_Archivos.py", ":material/folder_open:",
     "Cambios de archivos, vigilancia y reputación local u online por SHA-256."),
    ("Persistencia", "views/15_Persistencia.py", ":material/autorenew:",
     "Elementos que arrancan automáticamente: Run, Inicio, tareas y servicios."),
    ("Firewall", "views/16_Firewall.py", ":material/security:",
     "Paquetes bloqueados, orígenes y puertos observados."),
    ("Historial de análisis", "views/20_Historial.py", ":material/history_edu:",
     "Resultados anteriores de reglas, LLM y resúmenes."),
    ("Chat", "views/21_Chat.py", ":material/forum:",
     "Consultas a la evidencia mediante herramientas locales de sólo lectura."),
    ("Informes", "views/22_Informes.py", ":material/description:",
     "Generación, consulta y descarga de informes y expedientes."),
    ("Primeros pasos", "views/30_Primeros_pasos.py", ":material/rocket_launch:",
     "Diagnóstico de requisitos, fuentes, permisos y modelos."),
    ("IA local", "views/31_IA_local.py", ":material/smart_toy:",
     "Proveedor local, modelos por función, Ollama y llama.cpp."),
    ("Ajustes", "views/32_Ajustes.py", ":material/settings:",
     "Funciones, reglas activas, ciclo periódico, datos y bitácora."),
)


def _overview(settings, enabled: set[str]):
    a, b, c = st.columns(3)
    a.metric("Versión", APP_VERSION)
    b.metric("Reglas activas", f"{len(enabled)}/{len(RULE_IDS)}")
    c.metric("Operación", "Local")
    st.markdown("### Cómo funciona")
    st.write("Atalaya recolecta evidencia de Windows, la conserva localmente en SQLite y aplica reglas "
             "deterministas. La IA local es opcional: explica y resume, pero no crea el hecho detectado.")
    st.code("Recolectar  →  Normalizar y guardar  →  Aplicar reglas  →  Revisar alertas  →  Informar",
            language=None)
    left, right = st.columns(2)
    with left:
        st.markdown("#### Lo que hace")
        st.write("- Observa conexiones, procesos, memoria, accesos, archivos, persistencia y firewall.")
        st.write("- Conserva historial, evidencia y estado de las investigaciones.")
        st.write("- Funciona con reglas aunque no haya un modelo de IA disponible.")
    with right:
        st.markdown("#### Lo que no hace")
        st.write("- No ejecuta archivos ni órdenes propuestas por el LLM.")
        st.write("- No mata procesos, borra archivos, bloquea IP ni modifica el firewall.")
        st.write("- No envía evidencia a Internet sin una acción explícita.")
    st.caption(f"Datos locales: {settings.database_path.parent}")


def _sections():
    st.caption("Abra una sección para trabajar con esa parte del sistema.")
    for offset in range(0, len(SECTIONS), 3):
        columns = st.columns(3)
        for column, (name, page, icon, description) in zip(columns, SECTIONS[offset:offset + 3]):
            with column.container(border=True):
                st.markdown(f"#### {name}")
                st.write(description)
                page_link(page, f"Abrir {name}", icon)


def _rules(enabled: set[str]):
    st.caption("Las reglas crean alertas a partir de evidencia. Desactivarlas no detiene la recolección ni borra "
               "alertas anteriores.")
    state = st.segmented_control("Mostrar", ("Todas", "Activas", "Desactivadas"), default="Todas",
                                 key="guide-rule-state") or "Todas"
    search = st.text_input("Buscar regla", placeholder="R07, ransomware, memoria, RDP…",
                           key="guide-rule-search").casefold().strip()
    rows = []
    for rule_id in RULE_IDS:
        help_ = RULES[rule_id]
        active = rule_id in enabled
        if state == "Activas" and not active or state == "Desactivadas" and active:
            continue
        if search and search not in f"{rule_id} {help_.detects} {help_.check}".casefold():
            continue
        rows.append({"Estado": "Activa" if active else "Desactivada", "Regla": rule_id,
                     "Qué detecta": help_.detects, "Qué revisar": help_.check})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Estado": st.column_config.TextColumn(width="small"),
                                "Regla": st.column_config.TextColumn(width="small"),
                                "Qué detecta": st.column_config.TextColumn(width="large"),
                                "Qué revisar": st.column_config.TextColumn(width="large")},
                 key="guide-rules")
    page_link("views/32_Ajustes.py", "Cambiar reglas en Ajustes", ":material/tune:")


def _privacy():
    st.markdown("### Principios de seguridad")
    st.write("- La GUI y los proveedores locales deben escuchar únicamente en loopback.")
    st.write("- La evidencia se trata como datos no confiables, incluso dentro de prompts y documentos RAG.")
    st.write("- El chat usa herramientas cerradas, consultas parametrizadas y de sólo lectura.")
    st.write("- La reputación online envía únicamente el SHA-256 y requiere consentimiento explícito.")
    st.write("- Abrir una ubicación sólo invoca Explorer; nunca ejecuta el archivo.")
    st.warning("La base, los backups, informes y bitácoras pueden contener nombres de usuario, rutas, IP y actividad "
               "del equipo. Revise y seudonimice antes de compartirlos.")


def _glossary():
    terms = {
        "Alerta": "Hallazgo creado por una regla determinista y vinculado con evidencia.",
        "Baseline": "Comportamiento aprobado como habitual para reducir falsos positivos.",
        "Evidencia": "Dato observado en Windows; se conserva como información no confiable.",
        "Regla": "Comprobación reproducible R01–R17 que detecta un patrón concreto.",
        "LLM": "Modelo local que explica o resume; no sustituye a las reglas.",
        "RAG": "Búsqueda de fragmentos relevantes antes de responder una pregunta.",
        "Embedding": "Vector que representa texto para búsqueda semántica; no es un modelo de chat.",
        "Chunk": "Fragmento acotado de un documento o conversación usado en recuperación.",
        "Run": "Ejecución registrada de recolección, análisis o vigilancia.",
        "Estado partial": "La ejecución conservó resultados, pero alguna fuente o integración no estuvo disponible.",
    }
    st.dataframe(pd.DataFrame([{"Concepto": term, "Significado": meaning} for term, meaning in terms.items()]),
                 hide_index=True, width="stretch", key="guide-glossary")


def user_guide():
    settings, _, _, _ = context(window_applies=False)
    lang = st.session_state.get("language") or "es"
    hero("📖 Guía de Atalaya", f"Manual integrado de {DISPLAY_NAME}: funcionamiento, secciones, reglas y seguridad.")
    try:
        enabled = set(build_rule_config_service(settings).enabled_ids())
    except Exception as exc:
        enabled = set(RULE_IDS)
        st.warning(f"No se pudo leer la configuración de reglas: {type(exc).__name__}: {exc}")
    labels = (["Overview", "Sections", "Rules", "Privacy", "Glossary"] if lang == "en" else
              ["Cómo funciona", "Secciones", "Reglas", "Privacidad", "Glosario"])
    overview_tab, sections_tab, rules_tab, privacy_tab, glossary_tab = st.tabs(labels)
    with overview_tab:
        _overview(settings, enabled)
    with sections_tab:
        _sections()
    with rules_tab:
        _rules(enabled)
    with privacy_tab:
        _privacy()
    with glossary_tab:
        _glossary()
