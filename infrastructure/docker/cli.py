# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Read-only access to Docker through its CLI (JSON output). No new dependency, no administrator rights.

Only listing and inspection subcommands are ever run; the argument lists are fixed here and names coming from Docker
itself are passed as separate arguments (never through a shell). When Docker Desktop is stopped every call fails
fast and the caller shows that state instead of data.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

TIMEOUT = 20
READ_ONLY = {("version",), ("ps",), ("inspect",), ("image", "ls"), ("network", "ls"), ("network", "inspect"),
             ("volume", "ls"), ("volume", "inspect"), ("stats",), ("events",), ("scout", "quickview"), ("scout", "version")}


class DockerUnavailable(RuntimeError):
    pass


class DockerCLI:
    def __init__(self, executable: str | None = None, runner=subprocess.run):
        self.executable = executable or shutil.which("docker")
        self.runner = runner

    def _run(self, *args: str, timeout: float = TIMEOUT) -> str:
        if not self.executable:
            raise DockerUnavailable("Docker no está instalado")
        if not any(tuple(args[:len(prefix)]) == prefix for prefix in READ_ONLY):
            raise ValueError(f"Subcomando de Docker no permitido: {args[:2]}")
        environment = {**os.environ, "DOCKER_CLI_HINTS": "false"}
        try:
            completed = self.runner([self.executable, *args], capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=timeout, env=environment,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise DockerUnavailable("Docker no respondió a tiempo") from exc
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip().splitlines()
            raise DockerUnavailable(message[-1][:300] if message else f"docker terminó con código {completed.returncode}")
        return completed.stdout

    def _lines(self, *args: str) -> list[dict]:
        return [json.loads(line) for line in self._run(*args).splitlines() if line.strip().startswith("{")]

    def _array(self, *args: str) -> list[dict]:
        text = self._run(*args).strip()
        return json.loads(text) if text.startswith("[") else []

    def version(self) -> dict:
        data = json.loads(self._run("version", "--format", "{{json .}}", timeout=8) or "{}")
        server = data.get("Server") or {}
        if not server:
            raise DockerUnavailable("El motor de Docker no está en marcha (abra Docker Desktop)")
        return {"client": (data.get("Client") or {}).get("Version"), "server": server.get("Version"),
                "os": server.get("Os"), "context": (data.get("Client") or {}).get("Context")}

    def containers(self) -> list[dict]:
        """`docker inspect` of every container, running or not."""
        ids = [row["ID"] for row in self._lines("ps", "--all", "--no-trunc", "--format", "{{json .}}")]
        return self._array("inspect", "--type", "container", "--", *ids) if ids else []

    def stats(self) -> dict[str, dict]:
        rows = self._lines("stats", "--no-stream", "--no-trunc", "--format", "{{json .}}")
        return {row.get("ID", "")[:12]: row for row in rows}

    def images(self) -> list[dict]:
        return self._lines("image", "ls", "--all", "--no-trunc", "--format", "{{json .}}")

    def networks(self) -> list[dict]:
        ids = [row["ID"] for row in self._lines("network", "ls", "--no-trunc", "--format", "{{json .}}")]
        return self._array("network", "inspect", "--", *ids) if ids else []

    def volumes(self) -> list[dict]:
        names = [row["Name"] for row in self._lines("volume", "ls", "--format", "{{json .}}")]
        return self._array("volume", "inspect", "--", *names) if names else []

    def events(self, since: datetime, until: datetime | None = None) -> list[dict]:
        """Container events in a closed interval (returns at once instead of streaming)."""
        until = until or datetime.now(timezone.utc)
        return self._lines("events", "--since", str(int(since.timestamp())), "--until", str(int(until.timestamp())),
                           "--filter", "type=container", "--format", "{{json .}}")

    def scout_available(self) -> bool:
        try:
            self._run("scout", "version", timeout=10)
            return True
        except (DockerUnavailable, ValueError):
            return False

    def scout_quickview(self, image: str) -> str:
        """Docker Scout sends the image's package list to Docker's service: only on explicit request."""
        if image.startswith("-"):
            raise ValueError("Nombre de imagen no válido")
        return self._run("scout", "quickview", "--", image, timeout=120)
