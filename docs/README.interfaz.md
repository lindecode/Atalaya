# Interfaz y navegación

La navegación actual se define en `interfaces/gui/app.py`. Es la fuente de verdad; no deduzcas ubicaciones desde nombres históricos.

## Menús vigentes

- **Inicio**: Panel, En vivo, Alertas.
- **Investigar**: Buscar, Conexiones, Procesos y RAM, Accesos, Archivos, Persistencia, Firewall.
- **IA**: Historial de análisis, Chat, Informes.
- **Sistema**: Primeros pasos, IA local, Ajustes.

Responsabilidades:

- **Primeros pasos** diagnostica requisitos y permisos.
- **IA local** configura proveedor, instalación y modelos.
- **Ajustes** reúne configuración de funciones, ciclo automático, datos y bitácora.

No crees una segunda pantalla para la misma configuración. Si una función cambia de ubicación, actualiza `page_link`, ayudas, pruebas y README en el mismo commit; busca también el nombre anterior con `rg`.

## Presentación

- Usa `table_formatting.py` y `table_views.py` para fechas locales legibles, etiquetas, filtros y orden.
- Conserva UTC original en persistencia; no guardes el valor formateado.
- Gráficas y tablas se adaptan al contenedor y evitan desplazamiento lateral innecesario.
- Operaciones costosas o mutables muestran estado, confirmación cuando aplique, resultado y error recuperable.
- No insertes secretos ni HTML de evidencia sin escapar.

Prueba importación y renderizado básico de cada vista modificada, además de ruta y etiqueta del menú.
