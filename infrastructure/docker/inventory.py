# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from domain import docker
from infrastructure.docker.cli import DockerCLI, DockerUnavailable


def inventory(cli: DockerCLI | None = None) -> dict:
    """Everything the Docker tab shows, read now; `available=False` with the reason when the engine is off."""
    cli = cli or DockerCLI()
    try:
        version = cli.version()
        inspected = cli.containers()
    except DockerUnavailable as exc:
        return {"available": False, "error": str(exc)}
    sections = {}
    for name, read in (("stats", cli.stats), ("images", cli.images), ("networks", cli.networks), ("volumes", cli.volumes)):
        try:
            sections[name] = read()
        except DockerUnavailable as exc:  # one failing listing must not hide the others
            sections[name] = {} if name == "stats" else []
            sections.setdefault("warnings", []).append(f"{name}: {exc}")
    containers = [docker.container(raw, sections["stats"].get(str(raw.get("Id") or "")[:12])) for raw in inspected]
    return {"available": True, "version": version, "containers": containers, "images": sections["images"],
            "networks": sections["networks"], "volumes": sections["volumes"], "warnings": sections.get("warnings", [])}
