from __future__ import annotations

from domain import docker
from domain.models import CollectionRequest, CollectionResult, DockerObservation
from infrastructure.docker.cli import DockerCLI, DockerUnavailable


class DockerCollector:
    """Every container (running or stopped) with its published ports and risky settings; skipped without Docker."""

    name = "docker"

    def __init__(self, cli: DockerCLI | None = None):
        self.cli = cli or DockerCLI()

    def collect(self, request: CollectionRequest) -> CollectionResult:
        try:
            inspected = self.cli.containers()
            try:
                stats = self.cli.stats()
            except DockerUnavailable:
                stats = {}
        except DockerUnavailable as exc:
            return CollectionResult(self.name, "docker_observations", (), "skipped", (f"Docker: {exc}",))
        items = []
        for raw in inspected:
            model = docker.container(raw, stats.get(str(raw.get("Id") or "")[:12]))
            items.append(DockerObservation(request.now, model["id"], model["name"], model["image"], model["project"],
                                           model["state"], model["health"], model))
        return CollectionResult(self.name, "docker_observations", tuple(items), "ok")
