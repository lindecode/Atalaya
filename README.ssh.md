# Observabilidad SSH segura

`collect` registra sesiones SSH activas aunque usen puertos distintos de 22,
además del estado de los servicios `sshd` y `ssh-agent` en Windows. El chat
puede consultar esta evidencia mediante `get_ssh_observations`.

```powershell
& ..\.venv\Scripts\python.exe main.py collect
& ..\.venv\Scripts\python.exe main.py chat "¿Qué conexiones y túneles SSH están activos?"
```

Por privacidad sólo se conservan indicadores como `-L`, `-R`, `-D` y `-A`.
Destinos escritos en la línea de comandos, comandos remotos, claves privadas,
passphrases y contenido transportado por SSH se descartan antes de persistir.

**Desarrollo → SSH** dibuja estas sesiones en un mapa y añade los **túneles activos**: puertos reenviados por
VS Code Remote-SSH, por `ssh -L/-R/-D` y por `LocalForward`/`RemoteForward`/`DynamicForward` de `~/.ssh/config`.
Esos túneles se leen en vivo (la lista que guarda VS Code, los argumentos de los procesos `ssh` y el archivo de
configuración) y no se guardan. Detalles en [README/README.desarrollo-red.md](README/README.desarrollo-red.md).

Una sesión observada constituye evidencia, no una autorización para cerrarla.
El LLM opera en modo de lectura y debe citar los IDs consultados.
