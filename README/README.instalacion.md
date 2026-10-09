# Instalar Atalaya

Atalaya es un monitor de seguridad **local** para Windows. Observa las conexiones de red, los accesos, los archivos y la persistencia del equipo, detecta patrones sospechosos con reglas, y usa un LLM local (Ollama) para explicar las alertas. Nada sale del equipo, salvo la consulta opcional de reputación a VirusTotal, que envía solo el hash del archivo.

## Requisitos

| | Requisito | ¿Obligatorio? |
|---|---|---|
| Sistema | Windows 10 u 11 de **64 bits** | Sí |
| Espacio | ~330 MB para el programa, ~4 GB para los modelos y unos MB al día de datos (se purgan a los 30 días) | Sí |
| Python | **No hace falta** con el instalador ni con el ZIP portable, que ya lo incluyen. Solo para instalar desde el código fuente: Python 3.11 o superior | Según el método |
| **Ollama** | LLM local, gratuito. Sin él funcionan las reglas, las alertas y el panel, pero no hay explicaciones del LLM ni chat | Recomendado |
| Modelo de análisis y chat | `qwen3.5:4b`: 3,4 GB de disco y ~6 GB de RAM libre. Con menos de 8 GB de RAM: `qwen3.5:0.8b` (1 GB) | Con Ollama |
| Modelo de embeddings | `embeddinggemma`: 0,6 GB. Mejora la búsqueda del chat en la documentación | Opcional |
| GPU | Ollama la aprovecha si existe (NVIDIA o AMD); también funciona solo con CPU | Opcional |
| WebView2 Runtime | Permite que Atalaya se abra en **su propia ventana**. Windows 11 lo incluye y Windows 10 lo recibe con Edge. Si falta, Atalaya usa el navegador (`winget install Microsoft.EdgeWebView2Runtime` para instalarlo) | Recomendado |

Atalaya funciona **en segundo plano**: su icono aparece junto al reloj. Cerrar la ventana la oculta pero no detiene Atalaya; para salir del todo, usa el icono > **Salir de Atalaya**. Si prefieres el navegador, el mismo menú tiene **Abrir en el navegador**.
| Permisos | Ninguno para usar Atalaya. La configuración opcional *Configurar permisos* pide administrador **una vez** para leer accesos/RDP y el log del firewall | Opcional |
| Sysmon | Añade conexiones por proceso y borrados de archivos (ver `README.md`, fase 5) | Opcional |

Tras instalar, **Sistema > Primeros pasos** (o `diagnostico.bat`) comprueba todo esto en tu equipo y dice qué falta; los modelos se descargan en **Sistema > IA local**.

## Opción 1 · Instalador (recomendada)

1. Ejecuta `Atalaya-Setup-<versión>.exe`. **No pide administrador**: se instala solo para tu usuario en `%LOCALAPPDATA%\Programs\Atalaya`.
   - Como el instalador no está firmado digitalmente, Windows SmartScreen puede mostrar *"Windows protegió su PC"*. Pulsa **Más información > Ejecutar de todas formas**.
2. Si no tienes Ollama, el asistente ofrece **instalarlo con winget**, abrir su página de descarga o seguir sin él.
3. Elige si quieres acceso directo en el escritorio y que el monitor de archivos arranque al iniciar sesión.
4. Al terminar se abre Atalaya. Ve a **Sistema > Primeros pasos** para revisar el equipo y descarga los modelos en **Sistema > IA local** (unos 4 GB, una sola vez).
5. Opcional: menú Inicio > Atalaya > **Configurar permisos**. Después, cierra sesión y vuelve a entrar.

Para **actualizar**, ejecuta el instalador de la versión nueva encima: tus datos se conservan.
Para **desinstalar**, ve a *Configuración > Aplicaciones > Atalaya*. Te ofrece revertir los permisos y te pregunta si borrar tus datos.

## Opción 2 · ZIP portable

1. Descomprime `Atalaya-<versión>-portable.zip` donde quieras, por ejemplo en una memoria USB.
2. Abre `Atalaya\start\iniciar.bat`.
3. Los datos se guardan en `Atalaya\userdata\`, junto al programa, y no se crean accesos directos. Ollama se instala aparte, desde https://ollama.com/download/windows o con `winget install Ollama.Ollama`.

## Opción 3 · Desde el código fuente (desarrollo)

```powershell
winget install Python.Python.3.13      # si no tienes Python 3.11+
winget install Ollama.Ollama           # recomendado
git clone <repositorio> Atalaya
cd Atalaya
start\instalar.bat                     # crea .venv, instala el lock, modelos y accesos directos
```

- `requirements.txt`: dependencias de ejecución.
- `requirements-dev.txt`: añade `pytest`, para ejecutar los tests con `python -m pytest`.
- `requirements.lock.txt`: versiones exactas usadas por el instalador, el ZIP y la instalación desde código.

Para preparar solo la aplicación sin descargas posteriores de modelos use
`start\lib\instalar.ps1 -SinModelos`. `-Modelo NOMBRE` selecciona el modelo a
descargar y `-SinRed` verifica/prepara únicamente un runtime que ya contenga las
dependencias; no intenta instalar Python, paquetes, Ollama ni modelos.

## Dónde quedan los datos

| Método | Programa | Datos (base de datos, informes, historial del chat) |
|---|---|---|
| Instalador | `%LOCALAPPDATA%\Programs\Atalaya` | `%LOCALAPPDATA%\Atalaya` |
| ZIP portable | donde lo descomprimas | `userdata\` junto al programa |
| Código fuente | la carpeta del repositorio | `%LOCALAPPDATA%\Atalaya` |

La variable de entorno `ATALAYA_HOME` cambia la carpeta de datos en cualquier método. Las versiones anteriores guardaban los datos dentro de la carpeta del programa; la primera ejecución de la versión nueva los copia a la ubicación nueva y deja los originales intactos.

## Comandos útiles

```powershell
start\diagnostico.bat                 # o: python main.py doctor — requisitos y cómo resolverlos
python main.py models                 # modelos de Ollama instalados
python main.py models pull qwen3.5:4b # descargar un modelo
python main.py --version
```

En la versión instalada, cambia `python` por `"%LOCALAPPDATA%\Programs\Atalaya\runtime\python.exe"` y ejecuta los comandos desde esa carpeta.
