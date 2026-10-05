# Manual de operación de `Atalaya`

Este documento reúne la preparación manual de Windows y los mecanismos de
ejecución de la herramienta. `Atalaya` observa y recomienda: no bloquea
conexiones, no elimina archivos, no modifica el firewall y no instala Sysmon ni
tareas programadas.

## 1. Convenciones y seguridad

Los ejemplos parten de la raíz del repositorio:

```powershell
cd "C:\Users\rekqu\DZM Real\LLM\mlcon-new-york-2026-main"
$Python = (Resolve-Path ".\.venv\Scripts\python.exe").Path
$Main = (Resolve-Path ".\Atalaya\main.py").Path
```

- Use una terminal normal para GUI, chat, informes y recolección básica.
- Use una terminal **Ejecutar como administrador** únicamente para leer
  Security, tareas, servicios y otros datos protegidos.
- La base `Atalaya\data\atalaya.db` contiene nombres de usuario, rutas,
  procesos, IP y actividad del equipo. No la publique ni la adjunte a incidencias
  sin revisarla.
- Los comandos que cambian auditoría, firewall, Sysmon o Task Scheduler son
  preparativos manuales de Windows; la aplicación no los ejecuta.

## 2. Preparación inicial

Instale las dependencias en el entorno virtual compartido:

```powershell
& $Python -m pip install -r .\Atalaya\requirements.txt
```

Compruebe la CLI y ejecute las pruebas:

```powershell
& $Python $Main --help
& $Python -m pytest .\Atalaya\tests -q
```

Primera ejecución recomendada:

```powershell
& $Python $Main collect
& $Python $Main status
& $Python $Main analyze
& $Python $Main report
```

`partial` no significa que se hayan perdido todos los datos. Indica que al menos
un recolector no tenía permisos, su fuente no estaba habilitada o una dependencia
opcional —por ejemplo Sysmon— no estaba disponible.

## 3. Ollama local

Ollama debe escuchar solamente en loopback. Instale Ollama manualmente y, durante
la preparación, descargue el modelo configurado:

```powershell
ollama pull qwen3.5:4b
ollama serve
```

En otra terminal, compruebe el servicio local:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Para recuperación semántica, el modelo de embeddings predeterminado es local:

```powershell
ollama pull embeddinggemma:latest
$env:OLLAMA_EMBEDDING_MODEL = "embeddinggemma:latest"
```

Puede usar otro modelo de embeddings instalado mediante la variable anterior o
`rag index --embedding-model NOMBRE`. El modelo de chat y el de embeddings son
independientes.

También puede separar los modelos de análisis, chat y resumen:

```powershell
& $Python $Main models recommend
& $Python $Main models use qwen3.5:4b --role chat
& $Python $Main models use granite4.1:3b --role analysis
& $Python $Main models use qwen3.5:0.8b --role summary
```

La pantalla **Estado → Modelos por función** ofrece los mismos selectores. La
recomendación considera capacidades y tamaño de los modelos instalados; debe
contrastarse con los evals locales. El análisis estructurado usa baja
temperatura y una caché ligada a evidencia, modelo y versión del prompt.

La aplicación acepta exclusivamente `localhost`, `127.0.0.1` o `::1` como
`OLLAMA_HOST`. Para fijarlo explícitamente en una sesión:

```powershell
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
& $Python $Main analyze
```

Si Ollama está apagado, las reglas R01–R14 siguen funcionando. `analyze` termina
como `partial`, registra el error y `report` conserva las alertas deterministas.

## 4. Auditoría de Windows y ejecución elevada

Abra PowerShell como administrador. Antes de cambiar nada, consulte las
subcategorías disponibles; sus nombres pueden variar con el idioma de Windows:

```powershell
auditpol /get /category:*
auditpol /list /subcategory:*
```

Habilite como mínimo auditoría de inicio de sesión, administración de cuentas,
grupos y tareas programadas. En Windows en inglés, un ejemplo es:

```powershell
auditpol /set /subcategory:"Logon" /success:enable /failure:enable
auditpol /set /subcategory:"Special Logon" /success:enable /failure:enable
auditpol /set /subcategory:"User Account Management" /success:enable /failure:enable
auditpol /set /subcategory:"Security Group Management" /success:enable /failure:enable
auditpol /set /subcategory:"Other Object Access Events" /success:enable /failure:enable
wevtutil sl "Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational" /e:true
```

Use los nombres mostrados por `auditpol /list /subcategory:*` si el sistema está
en español. Después ejecute la recolección desde esa misma terminal elevada:

```powershell
cd "C:\Users\rekqu\DZM Real\LLM\mlcon-new-york-2026-main"
& .\.venv\Scripts\python.exe .\Atalaya\main.py collect
& .\.venv\Scripts\python.exe .\Atalaya\main.py status
```

Verifique en la salida que `security_events` indique `ok`. Si aparece `skipped`,
confirme que la terminal está elevada y que el registro Security es accesible.

### Prueba controlada de autenticación

Hágala solo en un equipo de laboratorio y con una cuenta de prueba que no pueda
bloquear una cuenta real. Genere los eventos necesarios, ejecute `collect` y
después `analyze`. No automatice intentos contra cuentas corporativas.

## 5. Registro del Firewall de Windows

En PowerShell como administrador:

```powershell
Set-NetFirewallProfile -All -LogBlocked True -LogAllowed False -LogMaxSizeKilobytes 16384
Get-NetFirewallProfile | Select-Object Name, LogBlocked, LogAllowed, LogFileName, LogMaxSizeKilobytes
```

La ruta habitual es:

```text
C:\Windows\System32\LogFiles\Firewall\pfirewall.log
```

Ejecute una recolección elevada y compruebe el estado:

```powershell
& $Python $Main collect
& $Python $Main status
```

El lector conserva un cursor de archivo y detecta rotación o truncamiento. Para
usar una copia de laboratorio sin cambiar la configuración global:

```powershell
$env:ATALAYA_FIREWALL_LOG = "C:\ruta\de\prueba\pfirewall.log"
& $Python $Main collect
```

## 6. Instalación manual de Sysmon

1. Descargue Sysmon desde la página oficial de Microsoft Sysinternals.
2. Obtenga y revise manualmente una configuración conocida, por ejemplo
   `sysmon-config` de SwiftOnSecurity. No ejecute configuraciones que no haya
   inspeccionado.
3. Extraiga Sysmon y abra PowerShell como administrador en esa carpeta.
4. Instálelo indicando el archivo de configuración revisado:

```powershell
.\Sysmon64.exe -accepteula -i .\sysmonconfig-export.xml
```

Compruebe el servicio y el canal:

```powershell
Get-Service Sysmon64, Sysmon -ErrorAction SilentlyContinue
wevtutil gli "Microsoft-Windows-Sysmon/Operational"
```

Recolecte y revise que `sysmon_network`, `sysmon_files` y
`sysmon_process_registry` aparezcan como `ok`:

```powershell
& $Python $Main collect
& $Python $Main status
```

Actualizar o desinstalar Sysmon queda bajo control del administrador y fuera del
alcance de `Atalaya`.

## 7. Mecanismos de ejecución

### Preparar RAG local

Después de instalar el modelo de embeddings, construya el índice:

```powershell
& $Python $Main rag index
& $Python $Main rag status
& $Python $Main rag search "cómo investigar un evento RDP 1149"
& $Python $Main rag eval
```

### Runbook: investigar un acceso RDP (evento 1149)

El evento 1149 del canal
`Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational`
indica que se autenticaron credenciales para una conexión RDP; debe
correlacionarse con Security 4624 (tipo de inicio 10), 4625 y 4648 antes de
concluir que hubo una sesión exitosa.

1. Ejecuta `collect` desde una terminal elevada para leer Security y el canal
   operacional de RDP.
2. Consulta **Accesos** en la interfaz o usa `chat` solicitando el usuario, IP,
   fecha y los IDs de evidencia del periodo investigado.
3. Correlaciona por IP, usuario y ventana temporal. Un 1149 aislado no prueba
   por sí solo que se creara una sesión de escritorio.
4. Revisa las alertas R03, si la IP está en la baseline y si es pública. No
   bloquees cuentas, direcciones ni procesos sin aprobación humana.
5. Conserva los IDs de eventos citados y exporta un backup antes de modificar
   la baseline o cerrar la alerta.

Los datos obtenidos de eventos se tratan como evidencia no confiable: nombres
de archivo, usuarios o mensajes nunca se ejecutan como instrucciones.

Para operar sin embeddings u observar una degradación controlada:

```powershell
& $Python $Main rag index --lexical-only
& $Python $Main rag search "activar firewall" --lexical-only
```

La indexación predeterminada toma los `.md` de `README/`, los `README*.md` de la
raíz y `agente.md`; si un documento se mueve o se borra, la siguiente
indexación completa lo retira del índice. Las rutas adicionales deben ser Markdown, estar dentro de
`Atalaya` y no ser enlaces simbólicos. Revise cualquier documento antes de
añadirlo: el índice lo considerará conocimiento confiable.

### Ejecución puntual

Úsela para inventario y análisis bajo demanda:

```powershell
& $Python $Main collect
& $Python $Main analyze
& $Python $Main report
```

### Monitor de archivos en vivo

Mantenga una terminal dedicada abierta:

```powershell
& $Python $Main watch
```

Finalice con Ctrl+C. El observador detiene sus hilos, guarda el lote pendiente y
cierra el `run`. No cierre la ventana a la fuerza salvo que sea imprescindible.

### Panel local

En otra terminal:

```powershell
& $Python $Main gui
```

Abra `http://127.0.0.1:8501`. Verifique la escucha:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501/_stcore/health
netstat -ano | Select-String ':8501'
```

La línea `LISTENING` debe mostrar `127.0.0.1:8501`, nunca `0.0.0.0:8501` ni la
IP LAN. Desde otro equipo de la red, la conexión a `http://IP-LAN:8501` debe
fallar.

Para verificar que el navegador no realiza peticiones externas:

1. Abra las herramientas de desarrollo del navegador.
2. Seleccione **Network** y limpie la lista.
3. Recorra todas las páginas y gráficos.
4. Confirme que los destinos son `127.0.0.1:8501` o recursos internos del mismo
   origen; no debe haber CDN, telemetría, mapas ni APIs externas.

### Chat local

```powershell
& $Python $Main chat "¿quién intentó conectarse por RDP esta semana?"
```

La respuesta muestra las herramientas llamadas y los IDs consultados. También
puede usar la página Chat de la GUI. El modelo no recibe capacidad de ejecutar
SQL libre ni comandos del sistema.

## 8. Ejecución automática con Task Scheduler

La forma recomendada es usar el lanzador incluido. No requiere guardar una
contraseña y ejecuta el ciclo sólo mientras el usuario tiene una sesión:

```powershell
.\start\automatizacion.bat activar 5
.\start\automatizacion.bat estado
.\start\automatizacion.bat desactivar
```

Cada ejecución llama a `main.py cycle`: selecciona el perfil configurado,
impide ciclos simultáneos y sólo inicia el análisis cuando hubo evidencia
nueva. La ventana temporal, el uso del LLM, las frecuencias de perfiles y la
retención se editan en **Estado → Configuración de análisis automático**.

La opción recomendada para `watch` es crear la tarea manualmente desde
**Task Scheduler**:

1. Elija **Create Task**, no *Create Basic Task*.
2. Nombre: `Atalaya watch`.
3. Disparador: **At log on** del usuario que se desea observar.
4. Acción, **Program/script**: ruta absoluta a `.venv\Scripts\python.exe`.
5. **Add arguments**: ruta absoluta a `Atalaya\main.py`, seguida de `watch`.
6. **Start in**: ruta absoluta de la carpeta `Atalaya`.
7. Use **Run only when user is logged on** para que las notificaciones locales
   sean visibles.
8. Active **Run with highest privileges** solo si se acepta que el monitor tenga
   acceso administrativo.
9. Configure **If the task is already running: Do not start a new instance**.
10. Ejecute la tarea manualmente una vez y confirme en `status` que existe un run
    `watch` activo.

Puede crear tareas separadas para `collect` y `analyze`, por ejemplo cada hora,
pero no ejecute varias instancias simultáneas del mismo comando. SQLite admite
lectores y escritor concurrentes, no sustituye el control de duplicados del
Task Scheduler.

## 9. Revisión de alertas y baseline

```powershell
& $Python $Main alert confirm 12 --note "Validado en el equipo"
& $Python $Main alert dismiss 13 --note "Actividad esperada"
& $Python $Main baseline approve remote_ip 192.0.2.10
```

Confirmar o descartar una alerta cambia su estado. Aprobar baseline declara una
entidad como comportamiento normal; son operaciones diferentes. Antes de aprobar
una IP, proceso, puerto o persistencia, revise su evidencia y procedencia.

## 10. Backup, retención y recuperación

Cree un backup consistente mientras la aplicación está en uso:

```powershell
& $Python $Main backup
```

Las copias se guardan en `Atalaya\data\backups`. Pruebe periódicamente que
pueden abrirse con una herramienta SQLite local y manténgalas protegidas como la
base principal.

Aplique retención:

```powershell
& $Python $Main purge --days 30
```

`purge` elimina datos anteriores al corte, conserva alertas confirmadas y sus
instantáneas de evidencia, y ejecuta `VACUUM`. Puede tardar y requerir un bloqueo
exclusivo; evítelo mientras `watch`, `collect` o `analyze` estén escribiendo.

Para restaurar una copia:

1. Detenga `watch`, GUI, `collect` y `analyze`.
2. Haga una copia adicional del archivo actual y de sus archivos `-wal`/`-shm`
   si existen.
3. Sustituya `data\atalaya.db` por una copia validada.
4. Ejecute `status`; las migraciones pendientes se aplicarán al abrir la BD.

La restauración es una operación manual y potencialmente destructiva: no la
realice mientras haya procesos usando la base.

## 11. Configuración temporal por entorno

Estas variables permiten pruebas aisladas sin modificar código:

```powershell
$env:ATALAYA_DB = "C:\ruta\aislada\atalaya.db"
$env:ATALAYA_REPORTS = "C:\ruta\aislada\reports"
$env:ATALAYA_FIREWALL_LOG = "C:\ruta\de\prueba\pfirewall.log"
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
```

Elimine una variable de la sesión para recuperar su valor predeterminado:

```powershell
Remove-Item Env:ATALAYA_DB
```

## 12. Diagnóstico rápido

### `collect` termina como `partial`

Revise cada recolector en la salida. Las causas habituales son terminal no
elevada, firewall sin logging, Sysmon ausente, carpetas inexistentes o procesos
protegidos que impiden leer sus metadatos.

### Ollama no responde

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
ollama list
```

Confirme que el modelo configurado está instalado y que `OLLAMA_HOST` no apunta a
otro equipo.

### `database is locked`

Espere a que termine `purge`/`VACUUM`, compruebe que no haya dos tareas idénticas
y vuelva a ejecutar. `watch`, análisis y GUI normales usan WAL y `busy_timeout`.

### La GUI no abre

```powershell
& $Python -m streamlit version
netstat -ano | Select-String ':8501'
```

No cambie `.streamlit\config.toml` para escuchar en `0.0.0.0`; el panel no tiene
autenticación y está diseñado únicamente para loopback.

## 13. Lista de validación pendiente por equipo

- [ ] Ejecutar `collect` en terminal elevada y confirmar `security_events: ok`.
- [ ] Verificar que los eventos 4624/4625 aparecen después de una prueba segura.
- [ ] Activar firewall logging y confirmar `windows_firewall: ok`.
- [ ] Instalar Sysmon manualmente y confirmar sus tres recolectores.
- [ ] Mantener `watch` activo, modificar/borrar archivos de laboratorio y revisar
      la evidencia resultante.
- [ ] Comprobar desde otro equipo que la GUI no responde por la IP LAN.
- [ ] Inspeccionar Network en el navegador y confirmar que no hay destinos externos.
- [ ] Crear y validar al menos un backup antes de depender de la retención.
