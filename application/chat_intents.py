"""Deterministic pre-retrieval: run the obvious tools for a question before the model sees it.

A small local model often fails to call a tool, or calls it with the wrong arguments; handing it the evidence up front
leaves it the easier job of reading and explaining. The model can still call any tool for more detail.
"""
from __future__ import annotations

import re
import unicodedata

MAX_TOOLS = 3

HOW_TO = re.compile(r"^(como|how|que (es|significa|hace|quiere decir)|what (is|are|does)|explica|explain|para que|"
                    r"por que|why|cuando (debo|deberia)|que debo|what should|guia|guide|pasos)\b")
PERIODS = ((r"\b(ultima hora|last hour|1h)\b", "1h"), (r"\b(hoy|today|24h|ultimo dia|last day)\b", "24h"),
           (r"\b(semana|week|7d|7 dias|7 days)\b", "7d"), (r"\b(mes|month|30d|30 dias|30 days)\b", "30d"))
# (pattern, tool, arguments); the first MAX_TOOLS distinct tools that match are run, in this order
INTENTS = (
    (r"\b(resumen|estado|situacion|panorama|novedades|que (ha )?pas|overview|summary|status|what happened|"
     r"estoy (seguro|en riesgo)|am i (safe|at risk)|todo bien|everything ok)", "get_overview", {}),
    (r"\b(alerta|alert|riesgo|risk|critic|grave|prioridad|priorit|urgent|amenaza|threat|incidente|incident|"
     r"sospech|suspicious|revisar primero|look at first)", "get_alerts", {}),
    (r"\b(rdp|escritorio remoto|remote desktop|inicio(s)? de sesion|logon|login|inicia(r|ron) sesion|acceso|"
     r"contrasena|password|autentic|authentic|fuerza bruta|brute|4625|4624|1149)", "get_auth_events", {}),
    (r"\b(puerto|port|escucha|listen|servidor|server|expuest|exposed)", "get_connections", {"direction": "listen"}),
    (r"\b(conexion|conexiones|connections?|ips?|red|redes|network|trafico|traffic|remot|destino|destination|"
     r"se conecta|connects?)\b", "get_connections", {}),
    (r"\b(persisten|inicio automatico|arranque|autorun|autostart|startup|tarea programada|scheduled task|"
     r"run key|servicio nuevo|new service)", "get_persistence_new", {"since": "7d"}),
    (r"\b(proceso|process|memoria|memory|ram|cpu|consum|programa(s)? (abierto|activo))", "get_processes", {}),
    (r"\b(reputacion|reputation|virustotal|hash|sha256|malware|virus|firmad|signed|ejecutable|executable)",
     "get_file_reputation", {"since": "30d"}),
    (r"\b(archivo|fichero|file|ransomware|cifrad|encrypt|renombr|renam|descarg|download)", "get_file_events", {}),
    (r"\b(ssh|tunel|tunnel)", "get_ssh_observations", {"since": "7d"}),
)


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(char for char in folded if not unicodedata.combining(char)).replace("¿", " ").split())


def period(question: str) -> str | None:
    text = _plain(question)
    return next((value for pattern, value in PERIODS if re.search(pattern, text)), None)


def plan(question: str) -> list[tuple[str, dict]]:
    """Tool calls to run before asking the model; a how-to question only searches the local documentation."""
    text = _plain(question).lstrip("¡!¿? ")
    if HOW_TO.match(text):
        return [("search_knowledge", {"query": question[:300], "top_k": 4})]
    when = period(question)
    calls: list[tuple[str, dict]] = []
    for pattern, tool, args in INTENTS:
        if len(calls) >= MAX_TOOLS:
            break
        if re.search(pattern, text) and all(name != tool for name, _ in calls):
            calls.append((tool, {**args, "since": when} if when else dict(args)))
    return calls
