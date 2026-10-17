# Desarrollo, red, Docker y SSH

La página **Inicio → Desarrollo** reúne lo que su equipo ofrece a la red y lo que usted ejecuta para programar:
servidores, contenedores de Docker, sesiones y túneles SSH, y avisos en vivo cuando alguien se conecta, le hace ping
o escanea sus puertos. Todo es de **solo lectura**: Atalaya muestra el comando que corregiría algo, pero nunca lo
ejecuta.

## Qué muestra la página

| Parte | Qué hay | De dónde sale |
|---|---|---|
| Resumen del LLM | Tres a cinco frases sobre servidores expuestos, clientes externos, contenedores y SSH | Datos agregados de la ventana temporal; el ciclo automático lo genera por turnos y hay un botón «Resumir ahora» |
| **¿Quién usa el puerto?** (cabecera) | Proceso, PID, direcciones, ruta, comando y, si es un túnel SSH, a dónde lleva | Sockets del equipo en este momento |
| Indicadores | Servidores, expuestos a la red, depuración expuesta, clientes externos ahora, avisos de red | En vivo y ventana temporal |
| **Qué revisar** | Hallazgos priorizados de servidores, Docker y SSH, cada uno con su corrección | Determinista, sin LLM |
| Mapa | Su PC en el centro, servidores alrededor (relleno = lenguaje, borde = alcance) y clientes por fuera | En vivo + avisos guardados (los clientes ya desconectados se dibujan en discontinuo) |
| Servidores | Tarjetas y tabla: puerto, lenguaje, aplicación Java, alcance, clientes, tiempo activo | En vivo |
| Docker | Contenedores por proyecto de Compose, redes (mapa), volúmenes, carpetas montadas, imágenes | CLI de Docker, solo lectura |
| SSH | Servidores a los que se conecta, túneles activos y quién entra a su propio SSH | En vivo + historial de sesiones |
| Línea de tiempo | Cuándo estuvo escuchando cada servidor | Recolecciones guardadas |
| Lenguajes | Memoria, procesos y puertos por runtime (Java, Node.js, Python, .NET, Go, Dart, Docker/WSL…) | En vivo |
| Avisos de red | Conexiones, pings, escaneos, servidores expuestos y problemas de contenedores | Vigilante de la bandeja |

Por defecto se ocultan los servicios propios de Windows (RPC 135 y 49152+, SMB 445, NetBIOS 139) y los ayudantes
locales de programas comunes; el interruptor **Todos los servidores** los muestra.

### Alcance de un servidor

- **Solo este equipo**: escucha en `127.0.0.1` o `::1`.
- **Red local**: escucha en una dirección privada concreta.
- **Todas las redes**: escucha en `0.0.0.0` o `::`. Es el error típico de `vite --host`, Flask o Spring sin
  `server.address`. «Qué revisar» propone cómo dejarlo solo en este equipo según el lenguaje, por ejemplo
  `server.address=127.0.0.1` (Spring) o `--host 127.0.0.1` (Vite/uvicorn).

## Avisos en vivo

Con Atalaya abierto junto al reloj, la bandeja vigila sin esperar al ciclo de recolección:

| Aviso | Cada | Cuándo |
|---|---|---|
| Conexión | 5 s | Un equipo de la red local o de Internet se conecta a uno de sus servidores |
| Ping | 5 s | El firewall descarta un ping dirigido a su equipo |
| Escaneo de puertos | 5 s | Una misma IP prueba 20 puertos o más en dos minutos |
| Servidor expuesto | 5 s | Un servidor nuevo empieza a escuchar fuera de `localhost` |
| Contenedor con problemas | 30 s | Un contenedor se reinicia en bucle (3 veces en 10 min), muere sin memoria (OOM) o pasa a `unhealthy` |

Cada aviso se repite como mucho una vez por hora para la misma IP y puerto. Arrancar o detener contenedores no
avisa. Todo queda registrado en **Desarrollo → Avisos de red** aunque desactive las notificaciones.

En **Sistema → Ajustes → Funciones**:

- **Avisos de red en vivo** activa o desactiva las notificaciones (activado por defecto).
- **IPs de confianza** lista direcciones o redes que nunca avisan, por ejemplo `192.168.1.50, 192.168.1.0/24`.

### Requisito para pings y escaneos

Ejecute una vez **Ajustes → Permisos ampliados → Configurar permisos** y cierre sesión. Esto activa la auditoría
**«Descarte de paquetes de la Plataforma de filtrado»** (evento 5152 del registro Security) y amplía ese registro a
128 MB para que los descartes no desplacen los inicios de sesión. Atalaya también lee `pfirewall.log`, pero el
servicio del firewall restablece sus permisos con frecuencia, así que el evento 5152 es la fuente fiable. Mientras
falte, Desarrollo lo indica con un aviso. `configurar-permisos.bat revertir` restaura la auditoría y el tamaño
anteriores.

## Reglas de alerta R18–R24

| Regla | Detecta | Severidad |
|---|---|---|
| R18 | Puerto de depuración abierto a la red: JDWP 5005, inspector de Node 9229, Chrome DevTools 9222, debugpy 5678, Jupyter 8888, Delve 2345 | Alta |
| R19 | Ping recibido (bloqueado por el firewall) | Baja en la red local, media desde Internet |
| R20 | Herramienta de túnel público conectada: ngrok, cloudflared, localtunnel, Dev Tunnels… | Alta |
| R21 | Puerto de contenedor publicado en todas las interfaces (`-p 5432:5432`) | Alta si es base de datos o panel de administración; media en otro caso |
| R22 | API de Docker en tcp 2375 sin TLS | Crítica si es accesible desde la red; alta en `localhost` |
| R23 | Contenedor con poder sobre el equipo: `--privileged`, socket de Docker montado, raíz del disco montada, `--network host`, `SYS_ADMIN` | Alta (media si solo es `--network host`) |
| R24 | Contraseñas o tokens en variables de entorno de un contenedor | Media |

R18, R20, R21, R23 y R24 se pueden **aprobar** como normales desde la alerta o con «Aprobar todo lo observado».

## Docker

Atalaya usa el CLI de Docker solo con comandos de lectura (`ps`, `inspect`, `stats`, `image ls`, `network`,
`volume`, `events`) y con salida JSON. Si Docker Desktop está apagado, la pestaña lo indica y las alertas usan lo
último que se recolectó.

- **Contenedores**: estado y salud (solo cuenta mientras el contenedor está en marcha), puertos publicados con su
  alcance, CPU y memoria, riesgos con su corrección.
- **Redes**: mapa con Docker en el centro, las redes alrededor y los contenedores por fuera; tabla con subred,
  gateway y miembros.
- **Volúmenes**: quién usa cada uno, cuáles no usa nadie y cuáles son anónimos; carpetas del equipo montadas en
  contenedores, marcando las sensibles.
- **Imágenes**: antigüedad, uso de `latest` e imágenes huérfanas, con `docker image prune` para copiar.
- **Docker Scout** (opcional, desactivado por defecto en Ajustes): busca vulnerabilidades conocidas de una imagen
  cuando usted lo pide. Envía la lista de paquetes de la imagen al servicio de Docker.

Del entorno de un contenedor **solo se guardan los nombres** de las variables que parecen secretos, nunca sus
valores. En el mapa principal y en los avisos, los puertos que abre Docker Desktop (`com.docker.backend`,
`wslrelay`) aparecen con el nombre del contenedor.

## SSH y túneles

La pestaña **SSH** dibuja su PC en el centro y alrededor los servidores a los que se conecta, con el alias de
`~/.ssh/config` cuando existe. Las sesiones abiertas ahora van en verde continuo; las vistas en la ventana, en
discontinuo. También aparecen los equipos que entran a su propio servidor SSH.

Los **túneles activos** se sitúan entre su PC y el servidor. Salen de tres fuentes:

1. **VS Code Remote-SSH**: los puertos que VS Code reenvía, automáticos o manuales. Por ejemplo, si el servidor abre
   `8090` y VS Code lo replica, verá `localhost:8090 → SSH Autotroph-agente → localhost:8090`. Atalaya lee la lista
   que guarda VS Code y solo cuenta los puertos que de verdad tiene abiertos.
2. **`ssh -L / -R / -D`** y `-o LocalForward=…` en la línea de comandos.
3. **`~/.ssh/config`**: `LocalForward`, `RemoteForward` y `DynamicForward` del host al que se conectó.

Cada túnel indica a dónde lleva, por dónde va, si escucha solo en su equipo o en la red y cuántas conexiones tiene.
Escribir su puerto en **¿Quién usa el puerto?** explica que es un túnel y que cerrarlo corta el reenvío, no el
servicio del servidor.

Riesgos que marca: túnel inverso (`-R`), reenvío del agente (`-A`) y un túnel que escucha en la red.

Privacidad: los túneles se leen en vivo y no se guardan. El historial de sesiones conserva solo las opciones
(`-L`, `-R`, `-D`, `-A`), nunca destinos ni comandos.

## Chat

El chat tiene dos herramientas en vivo para esta página:

- `get_dev_servers`: «¿quién se conectó a mi servidor del 8080?», «¿qué hay en el puerto 3000?», «mis servidores».
- `get_containers`: «¿mis contenedores de Docker tienen algún riesgo?», «¿qué volúmenes no uso?».

Desde **Qué revisar** hay preguntas rápidas que abren el chat con la pregunta ya enviada.

## Modelo para los resúmenes

Los resúmenes de todas las secciones usan el modelo del rol **resumen** (Sistema → IA local). Con modelos de menos
de 1,5B (por ejemplo `qwen3.5:0.8b`) el resumen puede contradecir los datos; use `qwen3.5:4b` o `gemma4:e2b`.
IA local avisa cuando el modelo elegido es demasiado pequeño.
