"""Canonical chat questions with what a good answer must do, to compare models on this machine's real evidence.

The checks are about behaviour, not wording: the right tool was consulted, the answer is not empty or evasive, it did
not fall back to the deterministic summary, it cites IDs when the evidence had rows, and it uses the right language.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from application.chat import DEFERS_TO_USER


@dataclass(frozen=True)
class EvalCase:
    question: str
    tools: tuple[str, ...]          # at least one of these must appear in the trace
    lang: str = "es"
    cite_ids: bool = True           # with evidence rows, the answer must name at least one number
    must_match: tuple[str, ...] = field(default_factory=tuple)  # regexes the answer must contain


CASES = (
    EvalCase("¿Qué alertas críticas hay?", ("get_alerts",)),
    EvalCase("¿Qué debería revisar primero?", ("get_alerts", "get_overview")),
    EvalCase("Dame un resumen del estado del equipo en las últimas 24 horas", ("get_overview",), cite_ids=False),
    EvalCase("¿Hubo inicios de sesión fallidos esta semana?", ("get_auth_events",)),
    EvalCase("¿Alguien se conectó por RDP?", ("get_auth_events",)),
    EvalCase("¿Qué puertos tengo abiertos?", ("get_connections",)),
    EvalCase("¿A qué IPs remotas se conecta el equipo?", ("get_connections",)),
    EvalCase("¿Qué procesos consumen más memoria?", ("get_processes",)),
    EvalCase("¿Se agregó persistencia nueva en los últimos 7 días?", ("get_persistence_new",)),
    EvalCase("¿Hay ejecutables con mala reputación?", ("get_file_reputation",), cite_ids=False),
    EvalCase("¿Cómo investigo un inicio de sesión RDP sospechoso?", ("search_knowledge",), cite_ids=False),
    EvalCase("What are the most important open alerts?", ("get_alerts",), lang="en"),
)

SPANISH = re.compile(r"(?i)\b(el|la|los|las|de|que|hay|no|en|para|una?)\b")
ENGLISH = re.compile(r"(?i)\b(the|is|are|there|of|and|to|no|in|for)\b")


def score(case: EvalCase, result: dict) -> dict:
    answer = result.get("answer") or ""
    trace = result.get("tool_calls") or []
    used = {call["name"] for call in trace}
    by_model = {call["name"] for call in trace if not call.get("prefetch")}
    had_rows = any(call.get("ids") for call in trace)
    words = SPANISH if case.lang == "es" else ENGLISH
    other = ENGLISH if case.lang == "es" else SPANISH
    checks = {
        "tool": bool(used & set(case.tools)),
        "answered": bool(answer.strip()) and not answer.startswith(("Sin respuesta", "Respuesta rechazada")),
        "not_evasive": not DEFERS_TO_USER.search(answer),
        "no_fallback": not result.get("fallback"),
        "cites": not (case.cite_ids and had_rows) or bool(re.search(r"\d", answer)),
        "language": len(words.findall(answer)) >= len(other.findall(answer)),
        "expected": all(re.search(pattern, answer) for pattern in case.must_match),
    }
    return {"question": case.question, "checks": checks, "passed": sum(checks.values()), "total": len(checks),
            "model_tools": sorted(by_model)}


def run(chat, cases=CASES, progress=None) -> dict:
    """`chat` is a ChatService (or anything with ask(question, lang=...)); errors count as a failed case."""
    results = []
    for case in cases:
        started = time.perf_counter()
        try:
            outcome = score(case, chat.ask(case.question, lang=case.lang))
        except Exception as exc:  # noqa: BLE001 - one broken answer must not stop the comparison
            outcome = {"question": case.question, "checks": {}, "passed": 0, "total": 7, "error": f"{type(exc).__name__}: {exc}"}
        outcome["seconds"] = round(time.perf_counter() - started, 1)
        results.append(outcome)
        if progress:
            progress(outcome)
    passed, total = sum(item["passed"] for item in results), sum(item["total"] for item in results)
    return {"score": round(100 * passed / total) if total else 0, "passed": passed, "total": total,
            "seconds": round(sum(item["seconds"] for item in results), 1), "cases": results}
