from __future__ import annotations

from typing import Protocol

from domain.models import CollectionRequest, CollectionResult


class Collector(Protocol):
    name: str

    def collect(self, request: CollectionRequest) -> CollectionResult: ...

