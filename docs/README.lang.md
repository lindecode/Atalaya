# Internacionalización y multi-idioma (i18n)

Atalaya implementa soporte bilingüe (**Español / Inglés**) con arquitectura modular centrada en el catálogo `shared/i18n.py`.

## Arquitectura

- **Catálogo central**: [`shared/i18n.py`](../shared/i18n.py) contiene los diccionarios de traducciones (`es` por defecto y `en`).
- **Función de consulta `t(key_path, lang=..., **kwargs)`**:
  - Resuelve claves jerárquicas como `common.rows_matching` o `charts.scope.public`.
  - Permite formateo de variables dinámicas con `.format(**kwargs)`.
  - Implementa fallback transparente al español (`es`) si una clave o traducción no existiese en otro idioma.
- **Configuración de idioma**:
  - Almacenada en la base de datos local a través de `AutomationConfig.language` (`es` | `en`).
  - Controlada en ejecución por la variable de entorno `ATALAYA_LANG` o el selector en la interfaz gráfica (`interfaces/gui/views/32_Ajustes.py`).
  - Respaldada en la sesión de Streamlit (`st.session_state["language"]`).

## Áreas cubiertas

1. **Tablas y esquemas de datos** (`tables`):
   - Encabezados de columnas traducibles en `interfaces/gui/table_views.py`.
   - Mapeos de códigos de eventos de Windows (`LOGON_TYPES`, `EVENT_NAMES`, `FILE_ACTIONS`, `PERSISTENCE_KINDS`).
   - Estados de alertas y severidades (`low`, `medium`, `high`, `critical`).
2. **Gráficos y visualizaciones** (`charts`):
   - Mapeo de alcance de red (`scope`: Internet, Red local/VPN, Este equipo).
   - Sentido de tráfico (`direction`: Entrante, Saliente, En escucha).
   - Encabezados de diagramas Sankey, mapas de exposición (treemap) y evolución temporal.
3. **Reglas de detección** (`rules`):
   - Descripciones operativas de lo que detecta cada regla R01–R16 (`detects`) y acciones recomendadas de revisión (`check`).
4. **Modelos LLM e IA local** (`llm`):
   - Directivas explícitas de idioma en el system prompt del LLM (`summary_system_prompt`, `chat_system_policy`).
   - Instrucciones estructuradas para el informe y exportación de incidentes (`export_instructions`).
   - Políticas de seguridad y delimitación de contexto (`untrusted_conversation_note`, `pseudonyms_on/off`).
5. **Instalador de Windows**:
   - Soporte para parámetro `-Idioma 'es'` / `-Idioma 'en'` en `start/lib/instalar.ps1` y pregunta interactiva si no se especifica.

## Reglas para agentes

- Al agregar nuevos textos, leyendas de UI, mensajes de error o prompts de IA, **agrégalos siempre a `shared/i18n.py`** en las secciones `ES_TRANSLATIONS` y `EN_TRANSLATIONS`.
- En el código de presentación o prompts, utiliza `t("ruta.de.clave", lang=lang)` en lugar de textos literales fijos.
- Mantén las pruebas unitarias en `tests/unit/test_i18n.py` al día con cualquier clave nueva.

