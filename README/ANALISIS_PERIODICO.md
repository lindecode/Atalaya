# Análisis periódico y retención

## Qué ejecuta el ciclo

La tarea **Atalaya - ciclo automático** llama periódicamente a `main.py cycle`.
Cada ciclo adquiere un bloqueo para evitar ejecuciones simultáneas y realiza:

1. Selección del perfil de recolección (`quick`, `standard` o `deep`).
2. Recolección incremental; los cursores evitan volver a leer eventos conocidos.
3. Reglas deterministas y, si está habilitado, explicación con el LLM, pero solo
   cuando aparecieron filas nuevas.
4. Mantenimiento: un backup por día y depuración cuando el perfil fue `deep`.

Con los valores iniciales —ciclo cada 5 minutos, `standard` cada 12 ciclos y
`deep` cada 288— se ejecuta aproximadamente un perfil standard por hora y uno
deep por día. Cambiar el intervalo de Task Scheduler no cambia automáticamente
los contadores guardados en la configuración.

La ventana de análisis y la retención son conceptos diferentes: la ventana
limita qué evidencia reciente evalúan las reglas y el LLM; la retención define
cuánto tiempo permanece la información en SQLite.

## Qué elimina la retención

En un ciclo `deep`, Atalaya crea primero el backup diario y después elimina los
datos anteriores al corte configurado. Se depuran conexiones, accesos, archivos,
firewall, Sysmon, análisis del LLM, caché, auditoría RAG, reputación, SSH, runs y
alertas no confirmadas. Después SQLite ejecuta `VACUUM` para recuperar espacio.

Las instantáneas detalladas de procesos usan por defecto una retención más corta
de 7 días para controlar el crecimiento. El ciclo de vida resumido de procesos
finalizados usa la retención general.

No se eliminan automáticamente:

- alertas confirmadas ni sus instantáneas de evidencia;
- baseline, preferencias y cursores de recolección;
- conversaciones, memoria RAG e índice de conocimiento;
- archivos de backup ya creados.

Por ello, los backups deben revisarse y archivarse o eliminarse mediante una
política externa. Antes de reducir la retención, cree y pruebe una copia.

## Configuración y ejecución

La configuración está en **Estado → Configuración de análisis automático**. El
campo «Intervalo recomendado» documenta la frecuencia esperada, pero la frecuencia
real pertenece a Task Scheduler. Para mantenerlas sincronizadas, vuelva a activar
la tarea con el mismo valor:

```powershell
.\start\automatizacion.bat activar 5
```

También puede ejecutar un ciclo o una depuración manual:

```powershell
.\.venv\Scripts\python.exe main.py cycle
.\.venv\Scripts\python.exe main.py purge --days 30
```

## Lectura de tablas

Las tablas de la interfaz convierten sus campos temporales ISO-8601 al formato
`DD/MM/AAAA HH:MM:SS` usando la zona horaria local del equipo. Cada tabla incluye
un panel **Buscar en esta tabla** para buscar texto en todas las columnas o
limitar la búsqueda a columnas concretas. El CSV descargado refleja las filas
filtradas y las fechas visibles.
