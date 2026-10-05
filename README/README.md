# Atalaya

Monitor local y de solo lectura para Windows 11. La Fase 1 recolecta conexiones,
eventos de autenticación, archivos recientes y mecanismos de persistencia en una
base SQLite local. No bloquea procesos, no modifica el firewall y no envía datos.

Para preparación de Windows, ejecución elevada, Sysmon, firewall, Task Scheduler,
backup y validaciones manuales consulte [README.man.md](README.man.md).

## Requisitos

Requisitos completos (Windows, Ollama, modelos, RAM, espacio) y las tres formas
de instalar (instalador `.exe`, ZIP portable, código fuente) en
**[README.instalacion.md](README.instalacion.md)**. Para compilar el instalador:
[../packaging/README.md](../packaging/README.md).

- Windows 10/11 x64. Python 3.11+ solo si se instala desde el código fuente
  (el instalador y el ZIP portable lo incluyen).
- Permisos de administrador opcionales. `start\configurar-permisos.bat` permite
  leer el registro Security sin elevación (grupo *Lectores del registro de
  eventos*). Sin ninguno de los dos se omite el registro Security;
  según la configuración del equipo, Windows también puede limitar tareas
  programadas, servicios o metadatos de procesos. La ejecución termina como
  `partial` y conserva todo lo que sí pudo recolectar.
- La base contiene actividad sensible del usuario. Vive en `%LOCALAPPDATA%\Atalaya`
  (o donde indique `ATALAYA_HOME`); protéjala con los controles de acceso del
  sistema. BitLocker o EFS son opciones externas.

## Instalación

**Usuarios:** `Atalaya-Setup-<versión>.exe` (ver [README.instalacion.md](README.instalacion.md)).

**Desde el código fuente:** doble clic en `start\instalar.bat` y, después,
`start\iniciar.bat` (o el acceso directo del escritorio). Los lanzadores y la
configuración de permisos sin administrador están descritos en
[README.start.md](README.start.md). Manualmente:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt       # ejecución
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # + tests
```

## Uso de Fase 1

```powershell
.\.venv\Scripts\python.exe Atalaya\main.py collect
.\.venv\Scripts\python.exe Atalaya\main.py status
```

## Análisis e informes (Fase 2)

```powershell
.\.venv\Scripts\python.exe Atalaya\main.py analyze
.\.venv\Scripts\python.exe Atalaya\main.py report
.\.venv\Scripts\python.exe Atalaya\main.py alert confirm 12 --note "Validado manualmente"
.\.venv\Scripts\python.exe Atalaya\main.py alert dismiss 13
.\.venv\Scripts\python.exe Atalaya\main.py baseline approve remote_ip 192.0.2.10
```

`analyze` siempre ejecuta R01–R14. Después intenta explicar las alertas con
Ollama en loopback. Si Ollama o el modelo no están disponibles, registra el
error y conserva las alertas deterministas. Los datos se delimitan y recortan
antes de entrar al prompt; nombres de archivo y demás evidencia nunca se
interpretan como instrucciones.

Cada `analyze` envía al LLM como máximo `llm_max_alerts` (40) alertas nuevas,
en lotes de `llm_batch_size` (8), empezando por las más graves. Solo pasan a
`analyzed` las alertas de los lotes que el modelo respondió; las de lotes
fallidos o fuera del tope quedan `new` para la siguiente ejecución.

### Baseline: qué es "normal" en este equipo

Las primeras `baseline_runs` (5) ejecuciones de `analyze` **aprenden**: aprueban
como normal los puertos en escucha, los orígenes de inicio de sesión y la
persistencia (servicios, tareas, claves Run, Startup) que observan, así que R03,
R04, R05 y R10 no alertan por lo que ya estaba. Después, solo lo nuevo genera
alertas. Las reglas que no dependen de la baseline (fuerza bruta, rutas
sospechosas, ransomware, escaneos, borrado de logs…) alertan siempre.

```powershell
# Aprobar de golpe todo lo observado hasta ahora y descartar las alertas que cubre
.\.venv\Scripts\python.exe Atalaya\main.py baseline learn
# Aprobar como normal la entidad de una alerta concreta (R03, R04, R05, R10)
.\.venv\Scripts\python.exe Atalaya\main.py alert approve 42
```

Aprender la baseline asume que el equipo está limpio en ese momento: algo que
ya estuviera comprometido quedaría aprobado. En la GUI, la página Alertas tiene
las mismas dos acciones.

### Elegir el LLM local

```powershell
# Lista los modelos de Ollama (* = el actual) y para qué sirve cada uno
.\.venv\Scripts\python.exe Atalaya\main.py models
# Guarda el modelo para analyze, chat y la GUI (se persiste en la BD local)
.\.venv\Scripts\python.exe Atalaya\main.py models use granite4.1:3b
# Usar otro modelo solo una vez
.\.venv\Scripts\python.exe Atalaya\main.py analyze --model qwen3.5:0.8b
```

Los modelos de embeddings (`all-minilm`, `embeddinggemma`) se listan pero no se
pueden elegir. El chat necesita un modelo con tool calling; `models` y la GUI
avisan si el elegido no lo tiene. En la GUI, el selector está en la barra
lateral.

## Interfaz local (Fase 3)

```powershell
.\.venv\Scripts\python.exe Atalaya\main.py gui
```

Abra `http://127.0.0.1:8501`. Streamlit escucha exclusivamente en loopback,
desactiva telemetría y no usa HTML inseguro para representar evidencia. Las
tablas pueden filtrarse, ordenarse y descargarse localmente como CSV.

## Firewall y monitor en vivo (Fase 4)

Active manualmente el registro de paquetes descartados desde PowerShell como
administrador:

```powershell
Set-NetFirewallProfile -All -LogBlocked True -LogAllowed False -LogMaxSizeKilobytes 16384
```

Después use `collect` para leer incrementalmente `pfirewall.log`. Para observar
creaciones, modificaciones, borrados y movimientos en vivo:

```powershell
.\.venv\Scripts\python.exe Atalaya\main.py watch
```

Finalice con Ctrl+C; el lote pendiente se guarda antes de cerrar. Para iniciarlo
con la sesión puede crear manualmente una tarea programada que ejecute ese mismo
comando. La aplicación no instala ni modifica tareas por sí sola.

## Sysmon y chat (Fase 5)

Sysmon es opcional. Descárguelo manualmente desde
[Microsoft Sysinternals](https://learn.microsoft.com/sysinternals/downloads/sysmon)
y use una configuración revisada, por ejemplo `sysmon-config` de
SwiftOnSecurity. La herramienta nunca lo descarga ni instala; únicamente intenta
leer `Microsoft-Windows-Sysmon/Operational` y se degrada si no existe.

```powershell
.\.venv\Scripts\python.exe Atalaya\main.py chat "¿quién intentó conectarse por RDP esta semana?"
```

El chat puede llamar únicamente a consultas parametrizadas y limitadas para
alertas, accesos, conexiones, archivos y persistencia. No acepta ni genera SQL
libre.

## RAG local y harness de seguridad

Indexe la documentación confiable. Si Ollama no dispone del modelo de embeddings,
FTS5 queda operativo y el comando informa la degradación:

```powershell
.\.venv\Scripts\python.exe Atalaya\main.py rag index
.\.venv\Scripts\python.exe Atalaya\main.py rag search "cómo investigar RDP"
.\.venv\Scripts\python.exe Atalaya\main.py rag status
.\.venv\Scripts\python.exe Atalaya\main.py rag eval
```

La evidencia exacta continúa consultándose mediante SQL parametrizado. RAG solo
recupera documentación local marcada como confiable o derivada, exige citas
`[K:id]`, limita el contexto y registra un hash de la consulta en lugar de su
texto. Los embeddings se cachean por hash del contenido.

## Mantenimiento

```powershell
.\.venv\Scripts\python.exe Atalaya\main.py backup
.\.venv\Scripts\python.exe Atalaya\main.py purge --days 30
```

Para operación periódica, `cycle` usa un perfil de lectura y sólo invoca el
análisis cuando ingresó evidencia nueva:

```powershell
.\.venv\Scripts\python.exe Atalaya\main.py collect --profile quick
.\.venv\Scripts\python.exe Atalaya\main.py cycle
.\Atalaya\start\automatizacion.bat activar 5
```

Los perfiles `standard` y `deep` se intercalan con la frecuencia configurada
en **Estado → Configuración de análisis automático**. El ciclo profundo crea el
backup diario antes de aplicar la retención.

El backup usa la API consistente de SQLite. La purga conserva las alertas
confirmadas y sus instantáneas de evidencia.

Los datos se guardan en `Atalaya/data/atalaya.db`. Los eventos de
Security requieren ejecutar la terminal como administrador. El canal operacional
de RDP se intenta de forma independiente y se omite con un aviso si no está
disponible.

## Arquitectura

`domain/` y `application/` no dependen de Windows, SQLite ni interfaces gráficas.
Los contratos viven en `ports/`; las implementaciones concretas están en
`infrastructure/`, y `bootstrap.py` realiza el ensamblaje. Esto permite reutilizar
los casos de uso con repositorios o recolectores alternativos.

## Autor

Desarrollado por **LindeCode** · <https://github.com/lindecode/Atalaya>

© 2026 LindeCode. Todos los derechos reservados; consulte [LICENSE](../LICENSE).
