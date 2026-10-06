# Atalaya

Monitor local de seguridad para Windows 10/11 x64. Recolecta evidencia del equipo,
aplica reglas deterministas y puede usar modelos locales de Ollama para explicar
alertas y consultar la información. La interfaz, la base de datos y el LLM operan
en el equipo; la reputación externa es opcional y envía únicamente hashes.

## Inicio rápido

- Usuario final: ejecute `Atalaya-Setup-<versión>.exe`.
- Portable: descomprima el ZIP y abra `start\iniciar.bat`.
- Desde código: abra `start\instalar.bat` y después `start\iniciar.bat`.
- Diagnóstico: abra `start\diagnostico.bat`.

No se requieren permisos de administrador para el uso normal. La configuración
opcional de permisos permite leer fuentes protegidas de Windows sin ejecutar la
aplicación elevada todos los días.

## Documentación

- [Instalación y requisitos](README/README.instalacion.md)
- [Lanzadores y operación diaria](README/README.start.md)
- [Manual de administración](README/README.man.md)
- [Uso, comandos y seguridad](README/README.md)
- [Arquitectura](README/README.arqu.md)
- [Construcción del instalador](packaging/README.md)

Atalaya conserva sus datos normalmente en `%LOCALAPPDATA%\Atalaya`. Antes de
usar la automatización, revise su configuración en **Estado → Configuración de
análisis automático** y cree un primer backup.
