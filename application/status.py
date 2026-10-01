from __future__ import annotations

from ports.repositories import CollectionRepository


class StatusService:
    def __init__(self, repository: CollectionRepository):
        self.repository = repository

    def execute(self) -> dict[str, object]:
        self.repository.initialize()
        return self.repository.status()

