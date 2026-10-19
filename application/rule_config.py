# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Persisted selection of deterministic detection rules."""
from __future__ import annotations

import json
from collections.abc import Iterable

from domain.rules import ALL_RULES


PREFERENCE_KEY = "disabled_detection_rules"
RULE_IDS = tuple(rule.__name__.upper() for rule in ALL_RULES)


class RuleConfigService:
    def __init__(self, repository, clock):
        self.repository = repository
        self.clock = clock

    def enabled_ids(self) -> tuple[str, ...]:
        self.repository.initialize()
        raw = self.repository.get_preference(PREFERENCE_KEY)
        if not raw:
            return RULE_IDS
        try:
            disabled = set(json.loads(raw))
        except (TypeError, json.JSONDecodeError):
            return RULE_IDS
        return tuple(rule_id for rule_id in RULE_IDS if rule_id not in disabled)

    def enabled_rules(self):
        enabled = set(self.enabled_ids())
        return tuple(rule for rule in ALL_RULES if rule.__name__.upper() in enabled)

    def save_enabled(self, enabled_ids: Iterable[str]) -> tuple[str, ...]:
        requested = set(enabled_ids)
        unknown = requested.difference(RULE_IDS)
        if unknown:
            raise ValueError(f"Reglas desconocidas: {', '.join(sorted(unknown))}")
        enabled = tuple(rule_id for rule_id in RULE_IDS if rule_id in requested)
        disabled = [rule_id for rule_id in RULE_IDS if rule_id not in requested]
        self.repository.initialize()
        self.repository.set_preference(PREFERENCE_KEY, json.dumps(disabled), self.clock.now_iso())
        return enabled
