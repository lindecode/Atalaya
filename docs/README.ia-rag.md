# IA, RAG y modelos locales

La IA complementa reglas deterministas; no sustituye la detección ni la decisión humana.

## Proveedores y modelos

- Proveedores: Ollama local, llama.cpp portable o IA desactivada.
- Descarga, registro y asignación requieren acción explícita del usuario.
- Las recomendaciones por RAM, CPU, VRAM y disco son orientativas.
- Separa modelos de chat/herramientas, análisis, resumen y embeddings.
- Si el proveedor falla, conserva reglas, búsqueda léxica y resultados parciales.

## Contexto y chunks

- Trocea por estructura Markdown antes de cortar por longitud.
- Preserva fuente, sección, hash, confianza y metadatos de cita.
- Crea chunks independientes con solape acotado; no dupliques fragmentos grandes en cada conversación.
- Resume y recupera conversaciones selectivamente. No conviertas cada turno en conocimiento confiable ni lo indexes globalmente de forma automática.

## Recuperación

- Combina FTS5 y embeddings; la búsqueda léxica es el fallback obligatorio.
- Entrega sólo el `top-k` necesario y registra IDs recuperados.
- Las citas corresponden a chunks realmente recuperados.
- Invalida embeddings por hash de contenido y modelo, no sólo por archivo.

## Harness y evaluación

- El harness controla política, herramientas permitidas, límites, saneamiento, iteraciones y validación.
- Un cambio de chunking, ranking, embedding o prompt ejecuta `rag eval` y añade casos si cambia el resultado esperado.
- Evalúa recuperación, citas, prompt injection, degradación sin proveedor y límites de contexto.
- No incorpores texto generado por LLM al corpus confiable sin revisión y cambio explícito de confianza.

La configuración está en **Sistema → IA local**; historial y consultas están bajo **IA**.
