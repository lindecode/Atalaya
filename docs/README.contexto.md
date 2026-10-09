# Contexto del producto

Atalaya es un monitor de seguridad local para Windows. Recolecta evidencia del equipo, la conserva en SQLite, detecta comportamientos mediante reglas deterministas y puede usar modelos locales para explicar, resumir y consultar resultados.

## Objetivos

- Mostrar conexiones, procesos, memoria, accesos, archivos, persistencia, firewall y telemetría disponible.
- Mantener historial consultable y aplicar retención controlada.
- Detectar primero con reglas auditables; usar el LLM como apoyo explicativo.
- Ofrecer CLI, panel Streamlit y lanzadores de Windows.
- Degradar de forma segura si faltan permisos, Sysmon, embeddings u Ollama.

## Límites

Atalaya observa y recomienda. No debe matar procesos, borrar archivos, bloquear IPs, cambiar el firewall, instalar Sysmon ni ejecutar acciones sugeridas por un modelo. Una futura respuesta activa requiere un diseño, permisos y auditoría separados.

La información del sistema es evidencia no confiable. Un nombre de proceso, ruta, evento, documento indexado o texto recuperado nunca se interpreta como una instrucción ejecutable.

## Modos principales

- `python main.py collect`: captura puntual.
- `python main.py cycle`: recolección y análisis periódico coordinado.
- `python main.py watch`: observación de archivos en vivo.
- `python main.py analyze`: reglas y explicación local opcional.
- `python main.py gui`: interfaz local.
- `python main.py doctor`: diagnóstico de requisitos.
- `python main.py --help`: inventario autoritativo de comandos.

Consulta `README/README.man.md` para operación y `README/README.instalacion.md` para instalación. No copies rutas absolutas de una máquina a código o documentación.
