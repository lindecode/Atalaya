from __future__ import annotations

from typing import Any, Protocol


class StructuredAnalyzer(Protocol):
    model: str
    def analyze(self, alerts: list[dict[str, Any]]) -> tuple[dict[str, Any], int, list[int]]:
        """Returns (validated result, prompt chars, ids of the alerts actually sent to the model)."""
        ...


class ModelCatalog(Protocol):
    def list_models(self) -> list[dict[str, Any]]: ...
