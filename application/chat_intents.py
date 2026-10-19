# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Deterministic pre-retrieval: run the obvious tools for a question before the model sees it.

A small local model often fails to call a tool, or calls it with the wrong arguments; handing it the evidence up front
leaves it the easier job of reading and explaining. The model can still call any tool for more detail.
"""
from __future__ import annotations

import re
import unicodedata

MAX_TOOLS = 3

# "¿Qué es un 4625?" asks for an explanation; "what are the open alerts?" asks for data, so only the article form counts
HOW_TO = re.compile(r"^(como|how|que (es una?|significa|hace|quiere decir)|what (is an?|does)|explica|explain|para que|"
                    r"por que|why|cuando (debo|deberia)|que debo|what should|guia|guide|pasos)\b")
PERIODS = ((r"\b(ultima hora|last hour|1h)\b", "1h"), (r"\b(hoy|today|24h|ultimo dia|last day)\b", "24h"),
           (r"\b(ayer|yesterday)\b", "48h"),
           (r"\b(semana|week|7d|7 dias|7 days)\b", "7d"), (r"\b(mes|month|30d|30 dias|30 days)\b", "30d"))
# (pattern, tool, arguments); the first MAX_TOOLS distinct tools that match are run, in this order
INTENTS = (
    (r"\b(resumen|estado|situacion|panorama|novedades|que (ha )?pas|overview|summary|status|what happened|"
     r"estoy (seguro|en riesgo)|am i (safe|at risk)|todo bien|everything ok|cambi|changed|preocup|worr|raro|"
     r"extran|anormal|unusual|weird|strange)", "get_overview", {}),
    (r"\b(alerta|alert|riesgo|risk|critic|grave|prioridad|priorit|urgent|amenaza|threat|incidente|incident|"
     r"sospech|suspicious|revisar primero|look at first)", "get_alerts", {}),
    (r"\b(rdp|escritorio remoto|remote desktop|inicio(s)? de sesion|logon|login|inicia(r|ron) sesion|acceso|"
     r"contrasena|password|autentic|authentic|fuerza bruta|brute|4625|4624|1149)", "get_auth_events", {}),
    (r"\b(docker|contenedor|container|compose|imagen(es)? de docker|docker images?|volumen(es)?|volumes?|"
     r"kubernetes|k8s)", "get_containers", {}),
    (r"\b(mis? servidor|my servers?|servidor(es)? de desarrollo|dev servers?|mis puertos|my ports|"
     r"(quien|alguien) se conect\w* a mis?|who connected to my|depuracion|debug port|spring|tomcat|localhost)",
     "get_dev_servers", {}),
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


IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
RULE = re.compile(r"\br(\d{2})\b")
EXECUTABLE = re.compile(r"\b([\w-]+\.exe)\b")
# "puerto 8080", "port 3000", ":5173", "localhost:8080"; not the minutes of "10:30"
PORT = re.compile(r"(?:\b(?:puerto|port)\s+|(?<![\d:]):)(\d{2,5})\b")


def _entities(text: str, when: str | None) -> list[tuple[str, dict]]:
    """A concrete IP, rule or executable in the question pins the tool and its filter."""
    calls: list[tuple[str, dict]] = []
    wide = {"since": when or "7d"}
    if match := IP.search(text):
        calls += [("get_connections", {"remote_ip": match.group(1), **wide}),
                  ("get_auth_events", {"source_ip": match.group(1), **wide})]
    if match := RULE.search(text):
        calls.append(("get_alerts", {"rule": f"R{match.group(1)}", **({"since": when} if when else {})}))
    if (match := PORT.search(text)) and int(match.group(1)) <= 65535:
        calls.append(("get_dev_servers", {"port": int(match.group(1))}))
    if match := EXECUTABLE.search(text):
        calls += [("get_processes", {"process": match.group(1), **wide}),
                  ("get_connections", {"process": match.group(1), **wide})]
    return calls


def plan(question: str) -> list[tuple[str, dict]]:
    """Tool calls to run before asking the model; a how-to question only searches the local documentation."""
    text = _plain(question).lstrip("¡!¿? ")
    when = period(question)
    calls: list[tuple[str, dict]] = []
    for name, args in _entities(text, when):  # "¿por qué R11…?" is about this machine's data, not a how-to
        if all(name != other for other, _ in calls):
            calls.append((name, args))
    if not calls and HOW_TO.match(text):
        return [("search_knowledge", {"query": question[:300], "top_k": 4})]
    for pattern, tool, args in INTENTS:
        if len(calls) >= MAX_TOOLS:
            break
        if tool == "get_connections" and args.get("direction") == "listen" and any(
                name == "get_dev_servers" for name, _ in calls):
            continue  # the live server list already answers "which ports are open"
        if re.search(pattern, text) and all(name != tool for name, _ in calls):
            # the live tools take no period
            live = tool in {"get_dev_servers", "get_containers"}
            calls.append((tool, {**args, "since": when} if when and not live else dict(args)))
    for index, (name, args) in enumerate(calls):
        bare = re.search(r"\b(\d{4,5})\b", text)  # "mi servidor del 8080"
        if name == "get_dev_servers" and "port" not in args and bare and int(bare.group(1)) <= 65535:
            calls[index] = (name, {**args, "port": int(bare.group(1))})
    return calls
