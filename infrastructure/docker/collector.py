# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
