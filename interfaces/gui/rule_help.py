# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Rule explanations for the GUI (defined in domain/rules/help.py) and alert status names."""
from __future__ import annotations

from domain.rules.help import RULES, RuleHelp  # noqa: F401  (re-exported for the GUI)
from shared.i18n import t, DEFAULT_LANGUAGE

STATUS_NAMES = {"new": "Nueva", "analyzed": "Analizada", "confirmed": "Confirmada", "dismissed": "Descartada"}
OPEN_STATUSES = ("new", "analyzed")


def status_names(lang: str = DEFAULT_LANGUAGE) -> dict[str, str]:
    statuses = t("tables.alert_status", lang=lang)
    return statuses if isinstance(statuses, dict) else STATUS_NAMES


def rule_help(rule_id: str, lang: str = DEFAULT_LANGUAGE) -> RuleHelp | None:
    data = t(f"rules.{rule_id}", lang=lang)
    if isinstance(data, dict) and "detects" in data and "check" in data:
        return RuleHelp(detects=data["detects"], check=data["check"])
    return RULES.get(rule_id)
