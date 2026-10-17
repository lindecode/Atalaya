# IA, RAG y modelos locales

La IA complementa reglas deterministas; no sustituye la detección ni la decisión humana.

## Proveedores y modelos

- Proveedores: Ollama local, llama.cpp portable o IA desactivada.
- Descarga, registro y asignación requieren acción explícita del usuario.
- Las recomendaciones por RAM, CPU, VRAM y disco son orientativas.
- Separa modelos de chat/herramientas, análisis, resumen y embeddings.
- **Sistema → IA local → Modelos por función** muestra también los modelos de embeddings instalados. Se seleccionan para indexación y búsqueda RAG; no pueden abrirse como chat.
- Si el proveedor falla, conserva reglas, búsqueda léxica y resultados parciales.
- El rol **resumen** necesita al menos unos 2B parámetros: con `qwen3.5:0.8b` el resumen de Desarrollo contradijo los datos que `qwen3.5:4b` resumió bien. IA local avisa por debajo de 1,5B.
- Los digests de resumen se redactan como frases ya interpretadas (p. ej. «java.exe en el puerto 8080 acepta conexiones de todas las redes») y empiezan por `puntos_a_revisar`: los modelos pequeños resumen frases con fiabilidad y malinterpretan campos sueltos.
- El chat tiene, además de las herramientas SQL, `get_dev_servers` (sockets en vivo y avisos de red) y `get_containers` (Docker en vivo). Ambas son de sólo lectura y devuelven filas compactas con resumen.

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
