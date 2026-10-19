# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


Verdict = Literal["trusted", "likely_safe", "unknown", "suspicious", "malicious"]


@dataclass(frozen=True, slots=True)
class ReputationResult:
    sha256: str
    path: str | None
    checked_at: str
    local: dict[str, Any]
    provider: str
    external: dict[str, Any] | None
    verdict: Verdict
    confidence: float
    reasons: tuple[str, ...]
