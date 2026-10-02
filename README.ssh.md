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

Una sesión observada constituye evidencia, no una autorización para cerrarla.
El LLM opera en modo de lectura y debe citar los IDs consultados.
