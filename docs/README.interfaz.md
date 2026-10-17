# Interfaz y navegación

La navegación actual se define en `interfaces/gui/app.py`. Es la fuente de verdad; no deduzcas ubicaciones desde nombres históricos.

## Menús vigentes

- **Inicio**: Guía de Atalaya, Panel, Desarrollo, En vivo, Alertas. La guía aparece primero, pero Panel continúa como página predeterminada.
- **Investigar**: Buscar, Conexiones, Procesos y RAM, Accesos, Archivos, Persistencia, Firewall.
- **IA**: Historial de análisis, Chat, Informes.
- **Sistema**: Primeros pasos, IA local, Ajustes.

Responsabilidades:

- **Primeros pasos** diagnostica requisitos y permisos.
- **IA local** configura proveedor, instalación y modelos.
- **Ajustes** reúne configuración de funciones, reglas de detección, ciclo automático, datos y bitácora.
- **Desarrollo** (`interfaces/gui/development.py`, con `docker_tab.py` y `ssh_tab.py`) muestra servidores, Docker, SSH y túneles, línea de tiempo, lenguajes y avisos de red. «¿Quién usa el puerto?» vive en su cabecera, no en una pestaña. Ver `README/README.desarrollo-red.md`.
- **Guía de Atalaya** es el manual integrado: explica el flujo, cada sección, las reglas y su estado real, privacidad y términos básicos. No modifica configuración.

En **Sistema → Ajustes → Funciones → Reglas de detección** se habilita o deshabilita cada regla. El cambio se aplica al próximo análisis; no detiene la recolección ni elimina alertas existentes. Todas las reglas están activas por defecto y “Activar todas” restaura esa selección.

No crees una segunda pantalla para la misma configuración. Si una función cambia de ubicación, actualiza `page_link`, ayudas, pruebas y README en el mismo commit; busca también el nombre anterior con `rg`.

## Presentación

- Usa `table_formatting.py` y `table_views.py` para fechas locales legibles, etiquetas, filtros y orden.
- Conserva UTC original en persistencia; no guardes el valor formateado.
- Gráficas y tablas se adaptan al contenedor y evitan desplazamiento lateral innecesario.
- Operaciones costosas o mutables muestran estado, confirmación cuando aplique, resultado y error recuperable.
- No insertes secretos ni HTML de evidencia sin escapar.

Prueba importación y renderizado básico de cada vista modificada, además de ruta y etiqueta del menú.

Los mapas de nodos usan `interfaces/gui/node_map.py` (`st.components.v2`, SVG propio, sin dependencias). Ese componente no está aislado de la página: los textos recolectados (procesos, IPs, imágenes) sólo se insertan con `textContent` o como atributos SVG, los colores se validan con un patrón hexadecimal y nunca se usa `innerHTML`.

Las capacidades disponibles dentro de la GUI deben invocar los servicios de `application/` mediante `bootstrap.py`. No indiques ejecutar un `.bat` desde una pantalla para completar una acción normal: los `.bat` son lanzadores opcionales de instalación, doble clic y operación externa.

**Archivos → Reputación de ejecutables** permite analizar una ruta sin ejecutar el archivo. El análisis local calcula el hash y comprueba Authenticode. La consulta en VirusTotal es opcional, requiere consentimiento explícito y envía únicamente el SHA-256; la clave escrita en la pantalla se usa para esa consulta y no se persiste.

Los detalles de alertas, archivos, reputación y procesos muestran acciones para rutas locales existentes. **Mostrar archivo** selecciona el elemento en Windows Explorer y **Abrir directorio** abre su carpeta; ninguna acción ejecuta el archivo. Se rechazan rutas relativas, URLs, recursos de red y enlaces simbólicos, y siempre se requiere una pulsación humana.

**Alertas** tiene búsqueda común por regla, severidad, título, entidad, evidencia, estado y nota. Su filtro **Ruta** busca fragmentos de ruta o nombres de archivo tanto en el resumen como en las instantáneas completas de evidencia; ambos filtros se pueden combinar. El modo **Agrupadas por ruta** usa la primera ruta absoluta identificable de cada alerta y conserva las que no tienen ruta en una sección separada, sin ocultarlas. **Archivos → Archivos repetidos** agrupa el último evento de cada ruta por SHA-256 y sólo considera duplicado un hash presente en rutas distintas; es un inventario de lo observado, no un escaneo completo ni una orden de eliminación.
