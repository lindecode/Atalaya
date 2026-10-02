# network-llm

Monitor local y de solo lectura para Windows 11. La Fase 1 recolecta conexiones,
eventos de autenticación, archivos recientes y mecanismos de persistencia en una
base SQLite local. No bloquea procesos, no modifica el firewall y no envía datos.

Para preparación de Windows, ejecución elevada, Sysmon, firewall, Task Scheduler,
backup y validaciones manuales consulte [README.man.md](README.man.md).

## Requisitos

- Windows 11 y Python 3.13 en el `.venv` de la raíz del repositorio.
- Permisos de administrador opcionales. Sin ellos se omite el registro Security;
  según la configuración del equipo, Windows también puede limitar tareas
  programadas, servicios o metadatos de procesos. La ejecución termina como
  `partial` y conserva todo lo que sí pudo recolectar.
- La base contiene actividad sensible del usuario. Proteja `network-llm/data/`
  con los controles de acceso del sistema; BitLocker o EFS son opciones externas.

## Instalación

Desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m pip install -r network-llm\requirements.txt
```

## Uso de Fase 1

```powershell
.\.venv\Scripts\python.exe network-llm\main.py collect
.\.venv\Scripts\python.exe network-llm\main.py status
```

## Análisis e informes (Fase 2)

```powershell
.\.venv\Scripts\python.exe network-llm\main.py analyze
.\.venv\Scripts\python.exe network-llm\main.py report
.\.venv\Scripts\python.exe network-llm\main.py alert confirm 12 --note "Validado manualmente"
.\.venv\Scripts\python.exe network-llm\main.py alert dismiss 13
.\.venv\Scripts\python.exe network-llm\main.py baseline approve remote_ip 192.0.2.10
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
.\.venv\Scripts\python.exe network-llm\main.py baseline learn
# Aprobar como normal la entidad de una alerta concreta (R03, R04, R05, R10)
.\.venv\Scripts\python.exe network-llm\main.py alert approve 42
```

Aprender la baseline asume que el equipo está limpio en ese momento: algo que
ya estuviera comprometido quedaría aprobado. En la GUI, la página Alertas tiene
las mismas dos acciones.

## Interfaz local (Fase 3)

```powershell
.\.venv\Scripts\python.exe network-llm\main.py gui
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
.\.venv\Scripts\python.exe network-llm\main.py watch
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
.\.venv\Scripts\python.exe network-llm\main.py chat "¿quién intentó conectarse por RDP esta semana?"
```

El chat puede llamar únicamente a consultas parametrizadas y limitadas para
alertas, accesos, conexiones, archivos y persistencia. No acepta ni genera SQL
libre.

## Mantenimiento

```powershell
.\.venv\Scripts\python.exe network-llm\main.py backup
.\.venv\Scripts\python.exe network-llm\main.py purge --days 30
```

El backup usa la API consistente de SQLite. La purga conserva las alertas
confirmadas y sus instantáneas de evidencia.

Los datos se guardan en `network-llm/data/network_llm.db`. Los eventos de
Security requieren ejecutar la terminal como administrador. El canal operacional
de RDP se intenta de forma independiente y se omite con un aviso si no está
disponible.

## Arquitectura

`domain/` y `application/` no dependen de Windows, SQLite ni interfaces gráficas.
Los contratos viven en `ports/`; las implementaciones concretas están en
`infrastructure/`, y `bootstrap.py` realiza el ensamblaje. Esto permite reutilizar
los casos de uso con repositorios o recolectores alternativos.
