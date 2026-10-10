from __future__ import annotations

import re


KNOWLEDGE_CITATION = re.compile(r"\[K:(\d+)\]")


from shared.i18n import t, DEFAULT_LANGUAGE

SYSTEM_POLICY_ES = t("llm.chat_system_policy", lang="es")
SYSTEM_POLICY_EN = t("llm.chat_system_policy", lang="en")
SYSTEM_POLICY = SYSTEM_POLICY_ES


def get_system_policy(lang: str = DEFAULT_LANGUAGE) -> str:
    return t("llm.chat_system_policy", lang=lang, default=SYSTEM_POLICY_ES)


class SecureChatHarness:
    def sanitize_question(self, question: str) -> str:
        return " ".join(question.replace("\x00", " ").split())[:4000]

    def tool_payload(self, name: str, rows):
        boundary = "TRUSTED_KNOWLEDGE" if name == "search_knowledge" else "UNTRUSTED_EVIDENCE"
        if isinstance(rows, dict):  # SQL tools return {"summary", "rows"}: totals first, then the sample
            return {"boundary": boundary, "tool": name, "summary": rows.get("summary", {}), "rows": rows.get("rows", [])}
        return {"boundary": boundary, "tool": name, "rows": rows}

    def validate_answer(self, answer: str, trace):
        allowed_knowledge = {str(value).removeprefix("K:") for item in trace if item["name"] == "search_knowledge" for value in item["ids"]}
        cited = set(KNOWLEDGE_CITATION.findall(answer or ""))
        invented = cited - allowed_knowledge
        if invented:
            return "Respuesta rechazada por citar conocimiento no recuperado: " + ", ".join(f"K:{value}" for value in sorted(invented))
        if allowed_knowledge and not cited:
            return (answer or "") + "\n\nAviso: la explicación no incluyó las citas de conocimiento recuperado y debe verificarse manualmente."
        return answer or "Sin respuesta del modelo."

