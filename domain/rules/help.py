"""What each detection rule means and what to check first (mirrors domain/rules/catalog.py)."""
from __future__ import annotations

from typing import NamedTuple


class RuleHelp(NamedTuple):
    detects: str
    check: str


RULES: dict[str, RuleHelp] = {
    "R01": RuleHelp("Muchos inicios de sesión fallidos (4625) desde una misma IP o contra una misma cuenta en pocos minutos.",
                    "¿La IP es de su red? ¿Alguien olvidó una contraseña o un servicio usa credenciales caducadas? "
                    "Si la IP es de Internet, bloquee el acceso remoto expuesto."),
    "R02": RuleHelp("Una ráfaga de intentos fallidos seguida de un inicio de sesión correcto desde la misma IP.",
                    "Trátelo como posible acceso no autorizado: confirme con el dueño de la cuenta, cambie la contraseña "
                    "y revise qué hizo esa sesión (procesos, persistencia, archivos)."),
    "R03": RuleHelp("Un acceso remoto interactivo (RDP) desde un origen que no está en la baseline.",
                    "¿Reconoce el origen? Si es Internet, la severidad sube a crítica. Si es legítimo, apruébelo como normal."),
    "R04": RuleHelp("Un inicio de sesión de red (tipo 3) de una cuenta de usuario desde un origen nuevo.",
                    "Suele ser un recurso compartido o una impresora. Confirme que el equipo de origen es suyo."),
    "R05": RuleHelp("Un proceso empezó a escuchar en un puerto que no estaba en la baseline.",
                    "¿El programa es conocido y necesita aceptar conexiones? Revise su alcance en Conexiones → Exposición."),
    "R06": RuleHelp("Un ejecutable que corre desde Temp, Descargas, Público o la Papelera tiene conexiones de red.",
                    "Compruebe la firma y la reputación del archivo (Archivos → Reputación) y a dónde se conecta."),
    "R07": RuleHelp("Una conexión saliente a un puerto asociado a herramientas de control remoto o malware (4444, 1337…).",
                    "Identifique el proceso y el destino; si no es una herramienta suya, aísle el equipo de la red."),
    "R08": RuleHelp("Muchas modificaciones, borrados o renombrados de archivos en las carpetas vigiladas en un minuto.",
                    "Puede ser una sincronización o una compilación… o cifrado por ransomware. Mire qué proceso escribe "
                    "y si aparecen extensiones nuevas."),
    "R09": RuleHelp("Señales de ransomware: notas de rescate, la misma nota en varias carpetas o renombrados masivos a una "
                    "extensión nueva.", "Desconecte el equipo de la red y no lo apague hasta revisar; conserve los archivos nota."),
    "R10": RuleHelp("Un elemento de arranque automático nuevo: clave Run, carpeta Inicio, tarea programada o servicio.",
                    "Verifique el comando y su ruta. Los instaladores legítimos crean estos elementos; si lo reconoce, "
                    "apruébelo como normal."),
    "R11": RuleHelp("Apareció un ejecutable o script nuevo fuera de Archivos de programa.",
                    "¿Lo descargó o instaló usted? Consulte su reputación por SHA-256 antes de ejecutarlo."),
    "R12": RuleHelp("Una misma IP intentó muchos puertos distintos y el firewall los bloqueó: escaneo de puertos.",
                    "Normal en equipos expuestos a Internet; preocupante si la IP es de su red local."),
    "R13": RuleHelp("Se borró el registro de auditoría de seguridad (evento 1102).",
                    "Es una técnica típica para ocultar actividad. Confirme quién lo hizo y revise lo ocurrido justo antes."),
    "R14": RuleHelp("Se creó una cuenta de usuario o se añadió una cuenta a un grupo (4720, 4732).",
                    "Confirme que el cambio fue intencional, sobre todo si el grupo es Administradores."),
    "R15": RuleHelp("La memoria de un proceso creció más de lo habitual durante la ventana.",
                    "Puede ser una fuga de memoria o un programa legítimo bajo carga; revise su historial en Procesos y RAM."),
    "R16": RuleHelp("Un proceso activo se ejecuta desde una ruta sospechosa y lo lanzó un intérprete (PowerShell, cmd, "
                    "wscript…) o consume mucha memoria.", "Revise su línea de comandos, su proceso padre y su firma."),
}
