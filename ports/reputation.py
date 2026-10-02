from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from domain.reputation import ReputationResult


class SignatureAnalyzer(Protocol):
    def inspect(self, path: Path) -> dict[str, Any]: ...


class ReputationProvider(Protocol):
    name: str
    def lookup_hash(self, sha256: str) -> dict[str, Any] | None: ...


class ReputationStore(Protocol):
    def initialize(self) -> None: ...
    def save(self, result: ReputationResult) -> None: ...
    def latest(self, limit: int = 100) -> list[dict[str, Any]]: ...
