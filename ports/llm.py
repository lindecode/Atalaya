from __future__ import annotations

from typing import Any, Protocol


class StructuredAnalyzer(Protocol):
    model: str
    def analyze(self, alerts: list[dict[str, Any]]) -> tuple[dict[str, Any], int]: ...

