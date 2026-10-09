# Guía de agentes de Atalaya

Este directorio es el punto de entrada para agentes humanos o de IA que mantengan Atalaya. Los documentos son temáticos para cargar sólo el contexto necesario.

## Lectura mínima

1. [Contexto del producto](README.contexto.md).
2. [Arquitectura y módulos](README.arquitectura.md).
3. [Reglas de desarrollo](README.desarrollo.md).
4. El documento especializado de la zona que vas a cambiar.

- [Seguridad y privacidad](README.seguridad.md): obligatorio para recolección, red, LLM, RAG, archivos, procesos, reputación y exportaciones.
- [Interfaz y navegación](README.interfaz.md): obligatorio para GUI, tablas o ubicación de menús.
- [IA, RAG y modelos](README.ia-rag.md): obligatorio para prompts, herramientas, chunks, embeddings y proveedores locales.
- [Pruebas y entrega](README.pruebas.md): validaciones y preparación del commit.

La documentación operativa para usuarios sigue en `README/`. `agente.md` conserva el plan histórico: no es la fuente normativa del estado actual.

## Regla de actualización

Todo cambio de comportamiento, comandos, navegación, dependencias, datos almacenados o controles de seguridad debe actualizar en el mismo commit el documento temático correspondiente y, si afecta al usuario, `README/`.

Si el código y estos documentos difieren, verifica código y pruebas, corrige la documentación y registra el cambio. No inventes una API, tabla, menú o garantía que no exista.
