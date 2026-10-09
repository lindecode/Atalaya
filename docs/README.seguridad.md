# Seguridad y privacidad

Estas reglas son restricciones del producto, no sugerencias.

## Red y servicios

- GUI, Ollama y llama.cpp escuchan únicamente en loopback: `127.0.0.1`, `localhost` o `::1`.
- No habilites acceso LAN, CORS amplio, telemetría, CDN ni recursos remotos en la GUI.
- Toda consulta externa es opt-in, minimiza datos y documenta qué sale del equipo. La reputación de ejecutables envía como máximo el SHA-256; nunca el binario, ruta, usuario o contenido sin consentimiento específico.

## Evidencia y LLM

- Trata toda evidencia como datos no confiables y delimítala en prompts.
- El modelo no ejecuta SQL libre, PowerShell, comandos, archivos ni URLs.
- Las herramientas del chat usan lista cerrada, argumentos validados, consultas parametrizadas, límites y sólo lectura.
- Valida salida estructurada, IDs citados y severidades. El LLM no crea el hecho detectado ni reduce silenciosamente una alerta crítica.
- RAG sólo recupera niveles de confianza permitidos. Una ruta nueva exige validar extensión, tamaño, pertenencia al proyecto y ausencia de enlaces simbólicos.

## Sistema operativo

- Solicita elevación sólo para fuentes que realmente la requieran.
- Los recolectores son de lectura; una corrección se muestra al humano y no se ejecuta automáticamente.
- No uses rutas o parámetros de eventos para invocar procesos.
- Para subprocesos usa argumentos fijos, `shell=False`, timeout y ejecutables identificados.

## Secretos y datos

- No registres claves API, tokens, prompts con evidencia completa ni mapas de seudónimos.
- Base, backups, informes y logs pueden contener datos sensibles; no se publican ni añaden a Git.
- Obtén claves del entorno o almacenes del sistema, nunca del código.
- Los errores visibles minimizan secretos y exposición de rutas.

Todo cambio en estas garantías requiere pruebas negativas que demuestren que el caso prohibido sigue rechazado.
