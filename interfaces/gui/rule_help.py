"""Rule explanations for the GUI (defined in domain/rules/help.py) and alert status names."""
from __future__ import annotations

from domain.rules.help import RULES, RuleHelp  # noqa: F401  (re-exported for the GUI)

STATUS_NAMES = {"new": "Nueva", "analyzed": "Analizada", "confirmed": "Confirmada", "dismissed": "Descartada"}
OPEN_STATUSES = ("new", "analyzed")
