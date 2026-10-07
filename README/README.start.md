# Arranque de Atalaya

Lanzadores de doble clic para instalar, abrir y mantener la herramienta sin escribir comandos. Cada `.bat` llama a su script en `lib\`, que es donde está la lógica.

## Primera vez

1. Doble clic en **`instalar.bat`**. Hace lo siguiente y se puede repetir sin problema:
   - Usa el entorno de Python existente (`Atalaya\.venv` o el `.venv` del repositorio). Si no hay ninguno, crea uno; necesita Python 3.11 o superior y, si falta, ofrece instalarlo con `winget`.
   - Instala las versiones exactas de `requirements.lock.txt`.
   - Comprueba Ollama (ofrece instalarlo con `winget`) y descarga `qwen3.5:4b` y `embeddinggemma` si faltan.
   - Inicializa la base de datos y el índice de documentación del chat.
   - Pregunta si crear accesos directos (escritorio y menú Inicio), si arrancar el monitor al iniciar sesión y si configurar los permisos.
2. Opcional: **`configurar-permisos.bat`**. Pide administrador **una sola vez** para:
   - añadir tu usuario al grupo *Lectores del registro de eventos*, con lo que se leen accesos, RDP y fuerza bruta (registro Security) y Sysmon sin ser administrador;
   - guardar los paquetes que bloquea el firewall en `%ProgramData%\Atalaya\firewall\`, una ruta que tu usuario puede leer.

   Antes de cambiar nada guarda el estado previo en `%ProgramData%\Atalaya\estado-previo.json`.
   Después hay que **cerrar sesión y volver a entrar**.

   Para deshacerlo: `configurar-permisos.bat revertir`. Restaura exactamente lo que había antes (si ya estabas en el grupo, sigues en él; si el log del firewall ya estaba activo, vuelve a su configuración anterior) y borra `%ProgramData%\Atalaya`. Si se configuró con una versión que no guardaba el estado, vuelve a los valores por defecto de Windows.

## Uso diario

| Archivo | Qué hace |
|---|---|
| `iniciar.bat` | Arranca Ollama si hace falta y abre el panel local. Prefiere `127.0.0.1:8501`; si está ocupado, elige otro puerto libre y valida que el proceso sea Atalaya |
| `recolectar.bat` | Ciclo completo: recolectar, analizar (reglas y LLM) e informe en `reports\` |
| `vigilar.bat` | Monitor de archivos en vivo (ransomware y cambios masivos). Ctrl+C para parar |
| `detener.bat` | Detiene el panel y el monitor. Ollama sigue en marcha, porque puede usarlo otra aplicación |
| `diagnostico.bat` | Revisa Python, dependencias, Ollama y modelos, servicios, permisos de cada fuente y base de datos. No cambia nada |

## Mantenimiento

| Archivo | Qué hace |
|---|---|
| `inicio-automatico.bat` | Sin argumentos, pregunta si activar o desactivar. También acepta `activar`, `desactivar` o `estado`. Usa un acceso directo en la carpeta Inicio del usuario y no necesita administrador |
| `limpiar-cache.bat` | Borra `__pycache__` y las cachés de pytest. No toca `data\`, `reports\` ni `.venv\` |
| `desinstalar.bat` | Quita accesos directos e inicio automático. Si detecta permisos configurados, ofrece restaurar el estado anterior (un aviso UAC). Si lo confirmas, borra el entorno propio. Los datos solo se borran si escribes `BORRAR` |

`automatizacion.bat activar 5` crea el ciclo programado. El diagnóstico valida
su ejecutable y su carpeta de trabajo; el desinstalador elimina esta tarea para
que no quede apuntando a una instalación inexistente.

## Notas

- **Nada se ejecuta como administrador en el día a día.** Solo `configurar-permisos.bat` lo pide, una vez. Sin esa configuración, la herramienta funciona igual pero se salta las fuentes protegidas y lo indica en el panel y en `diagnostico.bat`.
- **Los lanzadores fuerzan `OLLAMA_HOST=127.0.0.1`** en sus procesos, aunque tengas Ollama expuesto en la red para otros usos.
- **`detener.bat` cierra el monitor de golpe**, así que pueden perderse los eventos de archivos de los últimos 5 segundos. Para pararlo limpiamente, usa Ctrl+C en su ventana.
- Los `.ps1` se ejecutan con `-ExecutionPolicy Bypass` solo para ese proceso; no se cambia la política del sistema.
