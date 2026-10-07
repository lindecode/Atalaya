# Atalaya

Atalaya es un monitor local de seguridad para Windows 10/11 x64. Recolecta
evidencia del equipo, detecta comportamientos sospechosos mediante reglas
deterministas y, opcionalmente, utiliza modelos locales de Ollama para explicar
alertas y consultar la información en lenguaje natural.

La interfaz, SQLite y los modelos operan en el equipo. Atalaya no es un
antivirus ni reemplaza un EDR: está pensado como una herramienta de observación,
investigación y aprendizaje sobre la actividad de un equipo Windows.

## Qué incluye

- Inventario de procesos, conexiones, persistencia, firewall y archivos.
- Lectura incremental de eventos de Windows, incluidos Security, RDP y Sysmon
  cuando el sistema permite acceder a ellos.
- Reglas locales para accesos anómalos, conexiones, cambios de persistencia,
  actividad masiva de archivos y otros indicadores.
- Baseline aprobable para distinguir actividad conocida de novedades.
- Panel local, icono en el área de notificación y CLI para automatización.
- Informes Markdown, backups consistentes y retención configurable.
- Chat local con herramientas e historial de conversaciones.
- RAG híbrido local para consultar documentación propia.
- Reputación opcional de ejecutables mediante firma Authenticode y VirusTotal.

## Privacidad y conexiones externas

Por defecto, la evidencia y las conversaciones permanecen en el equipo. Las
funciones que pueden generar tráfico externo son explícitas:

| Función | Destino | Información enviada |
|---|---|---|
| Ollama | Sólo `localhost`, validado por la aplicación | Prompts y contexto al modelo local |
| Reputación en línea | VirusTotal, sólo al solicitar `--online` o `lookup` | Hash SHA-256; no se carga el archivo |
| Instalación y modelos | PyPI, Python.org y Ollama | Descargas de dependencias o modelos |

La clave opcional de VirusTotal se toma de `VIRUSTOTAL_API_KEY`; no debe
guardarse en el repositorio. Tampoco incluya bases de datos, informes o archivos
con evidencia al reportar un problema.

## Requisitos

- Windows 10 u 11 x64.
- Instalador oficial, o Python 3.11+ para ejecutar desde el código fuente.
- Ollama para análisis y chat con LLM; la recolección y las reglas funcionan sin él.
- WebView2 para la ventana integrada; si no está disponible puede usarse el navegador.
- Permisos de administrador sólo para configurar o leer determinadas fuentes
  protegidas. El uso diario no necesita ejecutarse elevado.

Sysmon es opcional. Atalaya nunca lo instala automáticamente; el manual de
administración explica cómo incorporarlo de forma controlada.

## Inicio rápido

### Instalador

Descargue `Atalaya-Setup-<versión>.exe`, complete el asistente y abra Atalaya
desde el menú Inicio. En la primera ejecución revise el diagnóstico, ejecute una
recolección y compruebe la configuración del análisis automático.

### ZIP portable

Descomprima el paquete y ejecute:

```bat
start\iniciar.bat
```

El marcador `portable` hace que los datos se conserven en `userdata\`, junto al
programa. No ejecute el ZIP directamente desde una carpeta comprimida.

### Desde el código fuente

```bat
git clone https://github.com/lindecode/Atalaya.git
cd Atalaya
start\instalar.bat
start\iniciar.bat
```

El instalador local crea `.venv`, instala las dependencias y prepara los accesos
necesarios. Para revisar el entorno sin iniciar la interfaz:

```bat
start\diagnostico.bat
```

## Primer recorrido recomendado

1. Ejecute el diagnóstico y resuelva únicamente los avisos de las fuentes que
   quiera utilizar.
2. Abra el panel y realice una recolección estándar.
3. Revise las alertas antes de aprobar elementos como normales.
4. Configure Ollama si desea explicaciones, chat o embeddings.
5. Cree un backup antes de activar la automatización.
6. Active el ciclo programado desde **Estado → Configuración de análisis automático**.

La baseline aprende durante las primeras ejecuciones, pero no aprueba por sí sola
actividad sospechosa. Use `baseline learn` sólo después de revisar el estado del
equipo.

## Datos y configuración

La ubicación predeterminada es `%LOCALAPPDATA%\Atalaya`:

```text
Atalaya\
├── data\atalaya.db
├── data\backups\
└── reports\
```

Variables de entorno admitidas:

| Variable | Propósito |
|---|---|
| `ATALAYA_HOME` | Cambia la raíz de datos |
| `ATALAYA_DB` | Cambia la ruta de SQLite |
| `ATALAYA_REPORTS` | Cambia el directorio de informes |
| `ATALAYA_FIREWALL_LOG` | Indica otro registro del Firewall de Windows |
| `OLLAMA_HOST` | Endpoint local de Ollama; sólo se aceptan direcciones loopback |
| `OLLAMA_EMBEDDING_MODEL` | Modelo local para embeddings RAG |
| `VIRUSTOTAL_API_KEY` | Activa consultas opcionales de reputación |

Ejemplo temporal en PowerShell:

```powershell
$env:VIRUSTOTAL_API_KEY = "su-clave-aqui"
.\.venv\Scripts\python.exe main.py reputation inspect "C:\ruta\programa.exe" --online
Remove-Item Env:VIRUSTOTAL_API_KEY
```

No coloque claves reales en scripts, archivos `.env`, capturas o reportes.

## CLI esencial

```powershell
.\.venv\Scripts\python.exe main.py doctor
.\.venv\Scripts\python.exe main.py collect --profile standard
.\.venv\Scripts\python.exe main.py cycle
.\.venv\Scripts\python.exe main.py status
.\.venv\Scripts\python.exe main.py analyze
.\.venv\Scripts\python.exe main.py report
.\.venv\Scripts\python.exe main.py gui
.\.venv\Scripts\python.exe main.py tray --monitor
.\.venv\Scripts\python.exe main.py backup
```

Use `python main.py --help` y `python main.py <comando> --help` para consultar
todas las opciones. Los perfiles `quick`, `standard` y `deep` equilibran tiempo
de ejecución y profundidad de recolección.

## Desarrollo y validación

Instale las dependencias de desarrollo y ejecute la suite desde la raíz:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

El proyecto separa dominio, casos de uso, infraestructura e interfaces. Consulte
la documentación de arquitectura antes de añadir recolectores o reglas y agregue
pruebas unitarias para cualquier cambio de comportamiento.

## Ediciones y servicios

**Atalaya Community** contiene la aplicación local completa disponible en este
repositorio: recolectores, reglas, CLI, GUI, RAG local e integración con Ollama.
Puede usarse y venderse conforme a MPL-2.0.

Professional y Enterprise son líneas comerciales planeadas para distribución
oficial firmada, soporte y administración organizacional. No todas esas funciones
forman parte de la versión actual. Consulte [COMMERCIAL.md](COMMERCIAL.md) para
conocer la separación entre código abierto, servicios y módulos comerciales.

## Documentación

- [Instalación y requisitos](README/README.instalacion.md)
- [Lanzadores y operación diaria](README/README.start.md)
- [Manual de administración y solución de problemas](README/README.man.md)
- [Uso completo, comandos y seguridad](README/README.md)
- [Arquitectura y fronteras de confianza](README/README.arqu.md)
- [Reputación de ejecutables](README.reputation.md)
- [Construcción y firma del instalador](packaging/README.md)
- [Análisis periódico, retención y lectura de tablas](README/ANALISIS_PERIODICO.md)
- [Seguridad y divulgación responsable](SECURITY.md)
- [Contribuciones](CONTRIBUTING.md)
- [Código de conducta](CODE_OF_CONDUCT.md)
- [Ediciones y servicios comerciales](COMMERCIAL.md)
- [Política de marcas](TRADEMARKS.md)

## Limitaciones

- Algunas fuentes de Windows no existen o no están habilitadas en todos los equipos.
- La ausencia de alertas no demuestra que un sistema esté limpio.
- Las explicaciones de un LLM pueden equivocarse; valide siempre contra la
  evidencia y las reglas deterministas.
- La calidad inicial depende de revisar y mantener una baseline apropiada.

## Licencia y autor

Atalaya Community se distribuye bajo **Mozilla Public License 2.0
(MPL-2.0)**. Puede utilizarse, modificarse y comercializarse respetando sus
condiciones. La licencia del código no concede derechos sobre las marcas Atalaya
o LindeCode. Consulte [LICENSE](LICENSE), [NOTICE](NOTICE) y
[TRADEMARKS.md](TRADEMARKS.md).
