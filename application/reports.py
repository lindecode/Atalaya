from __future__ import annotations

from pathlib import Path

from ports.clock import Clock
from settings import Settings


class ReportService:
    def __init__(self, repository, clock: Clock, settings: Settings):
        self.repository = repository
        self.clock = clock
        self.settings = settings

    def execute(self) -> Path:
        self.repository.initialize()
        alerts = self.repository.get_alerts()
        analysis = self.repository.latest_analysis()
        now = self.clock.now_iso()
        lines = ["# Informe de seguridad local", "", f"Generado: `{now}`", ""]
        if analysis and analysis.get("result_json"):
            result = analysis["result_json"]
            lines += ["## Resumen ejecutivo", "", result["summary"], "", f"Riesgo global: **{result['overall_risk']}**", ""]
            for incident in result.get("incidents", []):
                lines += [f"### Incidente · {incident['title']}", "", incident["narrative"], "",
                          f"Posible falso positivo: `{incident['false_positive_likelihood']}`", "",
                          "Recomendaciones:", ""]
                lines += [f"- {action}" for action in incident.get("recommended_actions", [])] + [""]
        else:
            lines += ["## Resumen ejecutivo", "", "LLM no disponible; el informe conserva las alertas deterministas.", ""]
        lines += ["## Alertas", ""]
        if not alerts:
            lines += ["No se encontraron alertas en la ventana analizada.", ""]
        for alert in alerts:
            lines += [f"### {alert['severity'].upper()} · {alert['rule_id']} · {alert['title']}", "",
                      f"ID: `{alert['id']}` · Estado: `{alert['status']}` · Fecha: `{alert['ts']}`", "",
                      "```json", __import__("json").dumps(alert["evidence"], ensure_ascii=False, indent=2), "```", ""]
        last_run = self.repository.latest_run("collect")
        skipped = []
        if last_run:
            skipped = [f"- {name}: {detail.get('warnings', [])}" for name, detail in (last_run.get("collectors") or {}).items() if detail.get("status") != "ok"]
        lines += ["## Qué no se pudo revisar", ""] + (skipped or ["Sin omisiones registradas en la última ejecución."]) + [""]
        self.settings.reports_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.reports_dir / (datetime_safe(now) + ".md")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path


def datetime_safe(value: str) -> str:
    return value[:16].replace("-", "").replace(":", "").replace("T", "_")
