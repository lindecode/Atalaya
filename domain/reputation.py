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
