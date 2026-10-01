# network-llm

Monitor local y de solo lectura para Windows 11. La Fase 1 recolecta conexiones,
eventos de autenticación, archivos recientes y mecanismos de persistencia en una
base SQLite local. No bloquea procesos, no modifica el firewall y no envía datos.

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

Los datos se guardan en `network-llm/data/network_llm.db`. Los eventos de
Security requieren ejecutar la terminal como administrador. El canal operacional
de RDP se intenta de forma independiente y se omite con un aviso si no está
disponible.

## Arquitectura

`domain/` y `application/` no dependen de Windows, SQLite ni interfaces gráficas.
Los contratos viven en `ports/`; las implementaciones concretas están en
`infrastructure/`, y `bootstrap.py` realiza el ensamblaje. Esto permite reutilizar
los casos de uso con repositorios o recolectores alternativos.
