"""Live Docker watch for the tray: container problems (restart loops, OOM kills, unhealthy) as notices.

Starts and stops are not notified (they are routine); only trouble is. Events are read in closed intervals, so a
stopped Docker Desktop costs one fast failing call per poll.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from application.network_watch import MUTE_SECONDS, Notice
from domain import docker

HISTORY_SECONDS = docker.RESTART_WINDOW
NAMES_SECONDS = 60


class DockerWatcher:
    def __init__(self, cli, now_iso: Callable[[], str], clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 monotonic: Callable[[], float] = time.monotonic):
        self.cli, self.now_iso, self.clock, self.monotonic = cli, now_iso, clock, monotonic
        self.since: datetime | None = None
        self.history: list[dict] = []   # recent events, so a restart loop spanning several polls is still seen
        self.muted: dict[tuple, float] = {}
        self.port_names: dict[int, str] = {}
        self.names_at: float | None = None
        self.trusted = ()               # set by the loop's config refresh; unused here

    def _refresh_names(self) -> None:
        if self.names_at is not None and self.monotonic() - self.names_at < NAMES_SECONDS:
            return
        self.names_at = self.monotonic()
        try:
            self.port_names = docker.port_names([docker.container(raw) for raw in self.cli.containers()])
        except Exception:
            self.port_names = {}

    def poll(self) -> list[Notice]:
        from infrastructure.docker.cli import DockerUnavailable
        now = self.clock()
        if self.since is None:  # the first look only sets the starting point: old events are not news
            self.since = now
            return []
        try:
            events = self.cli.events(self.since, now)
        except DockerUnavailable:
            self.port_names = {}
            return []
        self.since = now
        self._refresh_names()
        cutoff = now.timestamp() - HISTORY_SECONDS
        self.history = [event for event in self.history + events if (event.get("time") or 0) >= cutoff]
        notices = []
        for problem in docker.problems(self.history):
            key = (problem["container"], problem["problem"])
            if self.monotonic() - self.muted.get(key, -MUTE_SECONDS - 1) < MUTE_SECONDS:
                continue
            self.muted[key] = self.monotonic()
            notices.append(Notice(self.now_iso(), "docker", None, None, None, problem["container"],
                                  f"{problem['problem']}: {problem['detail']}"))
        return notices


def since_minutes(minutes: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)
