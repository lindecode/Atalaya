# Compilar la distribución de Atalaya

`packaging\build.bat` (o `build.ps1`) genera en `dist\`:

| Archivo | Contenido |
|---|---|
| `Atalaya-Setup-<versión>.exe` | Instalador por usuario, sin administrador (Inno Setup). Unos 70 MB |
| `Atalaya-<versión>-portable.zip` | La misma carpeta lista para usar, con los datos junto al programa. Unos 105 MB |

Ambos incluyen el **Python embebido oficial** y todas las dependencias ya instaladas, así que el equipo de destino no necesita Python ni conexión a Internet para instalar. Ollama y sus modelos no se incluyen: los ofrece el asistente de instalación y la página *Primeros pasos*.

## Requisitos del equipo de compilación

| Herramienta | Para qué | Instalación |
|---|---|---|
| Windows 10/11 x64 | El paquete es solo para Windows | — |
| Python **3.13** (la misma versión menor que el embebido) | `pip` resuelve las ruedas para `cp313-win_amd64` | `winget install Python.Python.3.13` |
| git | El paquete se arma con los archivos versionados (`git ls-files`): nada de cachés, datos ni secretos locales | `winget install Git.Git` |
| Inno Setup 6.3+ | Compila el `.exe`. Sin él, `build.ps1 -SinInstalador` genera solo el ZIP | `winget install JRSoftware.InnoSetup -e` |
| Internet | Solo la primera vez: Python embebido (se guarda en `packaging\cache\`) y ruedas de PyPI | — |

## Uso

```powershell
packaging\build.bat                     # carpeta + ZIP portable + instalador
packaging\build.ps1 -SinInstalador      # sin Inno Setup: solo carpeta y ZIP
packaging\build.ps1 -SinZip -SinPrueba  # iteración rápida del instalador
```

Qué hace `build.ps1`, en orden:

1. Lee la versión de `shared\about.py` (`APP_VERSION`), que es la única fuente.
2. Copia a `build\Atalaya\` los archivos versionados, excepto `tests\` y `packaging\`. Avisa si hay cambios sin commit.
3. Descarga el Python embebido indicado en `versions.json`, **verifica su SHA-256** y configura `python313._pth` para que encuentre las dependencias, la aplicación (`..`) e `import site` (necesario para las DLL de pywin32).
4. Instala `requirements.lock.txt` en `runtime\Lib\site-packages` con ruedas binarias para `win_amd64`/`cp313` (`--no-deps`: el lock ya incluye todo). Quita las suites de tests de las librerías y las plantillas de desarrollo de Streamlit.
5. **Prueba de humo** con el Python del paquete: importaciones, `--version`, base de datos y `doctor`.
6. Comprueba que ninguna ruta relativa supera 170 caracteres. Windows corta en 260, y la instalación añade unos 46 más el nombre de usuario.
7. Genera el ZIP (con el archivo `portable`) y compila `atalaya.iss` con Inno Setup.

## Actualizar dependencias o Python

- **Dependencias**: edita `requirements.txt`, ejecuta `packaging\actualizar-lock.ps1` (resuelve en un entorno limpio y reescribe `requirements.lock.txt`), revisa el diff y compila.
- **Python embebido**: cambia `version`, `url` y `sha256` en `versions.json`. El hash debe coincidir con el de `https://www.python.org/api/v2/downloads/release_file/?release=<id>`. Si cambia la versión menor (3.13 a 3.14), regenera también el lock con esa versión.
- **Versión de Atalaya**: solo `APP_VERSION` en `shared\about.py`.

## El instalador (`atalaya.iss`)

- **Instalación por usuario** (`PrivilegesRequired=lowest`) en `%LOCALAPPDATA%\Programs\Atalaya`. Los datos del usuario viven en `%LOCALAPPDATA%\Atalaya`, fuera de la carpeta del programa, así que actualizar o reinstalar no los toca.
- **Accesos directos:** menú Inicio (Atalaya, Recolectar y analizar, Diagnóstico, Configurar permisos, Detener, Desinstalar). Escritorio y arranque automático del monitor son tareas opcionales.
- **Ollama:** si no lo detecta, una página del asistente ofrece instalarlo con `winget`, abrir su web o seguir sin él.
- **Actualizaciones:** el `AppId` es fijo, así que una versión nueva se instala encima. Primero borra los módulos antiguos para no mezclarlos, y cierra Atalaya si está abierto (Restart Manager).
- **Desinstalación:** ejecuta `start\lib\desinstalar.ps1 -DesdeDesinstalador`, que detiene Atalaya, ofrece revertir los permisos y pregunta por los datos. En modo silencioso (`/VERYSILENT`) solo detiene Atalaya y conserva datos y permisos.

Instalación desatendida (despliegues):

```powershell
Atalaya-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /TASKS="desktopicon"
```

## Firma digital (recomendada antes de distribuir)

Sin firma, SmartScreen muestra "editor desconocido". Con un certificado de firma de código:

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f certificado.pfx /p <clave> dist\Atalaya-Setup-1.0.0.exe
```

Inno Setup puede firmar también el desinstalador con la directiva `SignTool` (ver su documentación).
