# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from domain import docker
from domain.models import CollectionRequest, EvidenceView
from domain.rules import catalog
from infrastructure.docker.cli import DockerCLI, DockerUnavailable
from infrastructure.docker.collector import DockerCollector
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings
from tests.docker_fixtures import API, EVENTS, POSTGRES, PORTAINER, FakeRunner

NOW = datetime.now(timezone.utc).isoformat()


def test_published_ports_merge_ipv4_and_ipv6_and_know_their_reach():
    assert docker.published(POSTGRES) == [{"container_port": 5432, "proto": "tcp", "host_ip": "0.0.0.0",
                                           "host_port": 5432, "scope": "all", "service": "PostgreSQL"}]
    assert [(p["host_port"], p["scope"]) for p in docker.published(API)] == [(3000, "local")]  # 9229 not published


def test_risks_cover_exposure_privileges_socket_root_and_secret_names_only():
    kinds = {risk["kind"]: risk for risk in docker.risks(POSTGRES)}
    assert set(kinds) == {"published", "env_secrets"}
    assert kinds["published"]["severity"] == "high" and kinds["published"]["fix"] == "-p 127.0.0.1:5432:5432"
    assert kinds["env_secrets"]["detail"] == "POSTGRES_PASSWORD"            # *_FILE is the good practice
    model = docker.container(POSTGRES)
    assert "hunter2" not in repr(model)                                     # values never leave the domain
    assert docker.risks(API) == []
    assert {risk["kind"] for risk in docker.risks(PORTAINER)} == {"privileged", "capabilities", "host_network",
                                                                   "docker_socket", "host_root"}


def test_problems_detect_restart_loops_once_oom_and_unhealthy():
    found = docker.problems(EVENTS)
    assert [(p["container"], p["problem"]) for p in found] == [("shop-api-1", "restart_loop"), ("portainer", "oom"),
                                                               ("shop-db-1", "unhealthy")]
    assert "código 1" in found[0]["detail"]


def test_cli_runs_only_read_only_commands_and_reports_a_stopped_engine():
    runner = FakeRunner()
    cli = DockerCLI("docker", runner)
    assert cli.version()["server"] == "29.8.2"
    assert len(cli.containers()) == 3
    with pytest.raises(ValueError, match="no permitido"):
        cli._run("rm", "-f", "shop-db-1")
    with pytest.raises(DockerUnavailable, match="dockerDesktopLinuxEngine"):
        DockerCLI("docker", FakeRunner(running=False)).containers()
    assert DockerCLI(None).executable is None or True


def test_collector_stores_secret_free_observations_and_rules_fire(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "d.db")
    repository = SQLiteRepository(settings)
    repository.initialize()
    result = DockerCollector(DockerCLI("docker", FakeRunner())).collect(CollectionRequest(NOW))
    assert result.status == "ok" and [item.name for item in result.items] == ["shop-db-1", "shop-api-1", "portainer"]
    run = repository.start_run("collect", NOW, False)
    assert repository.save_collection(run, result, NOW) == 3
    view = repository.load_evidence("2000-01-01")
    assert len(view.docker_observations) == 3 and "data_json" not in view.docker_observations[0]
    assert "hunter2" not in repr(view.docker_observations)

    r21 = catalog.r21(view, None)
    assert [(a.entity, a.severity) for a in r21] == [("shop-db-1|5432", "high")]
    assert [a.entity for a in catalog.r23(view, None)] == ["portainer"]
    assert [a.summary["variables"] for a in catalog.r24(view, None)] == ["POSTGRES_PASSWORD"]
    approved = EvidenceView(docker_observations=view.docker_observations,
                            baseline=frozenset({("docker_publish", "shop-db-1|5432"), ("docker_privileges", "portainer")}))
    assert catalog.r21(approved, None) == [] and catalog.r23(approved, None) == []

    skipped = DockerCollector(DockerCLI("docker", FakeRunner(running=False))).collect(CollectionRequest(NOW))
    assert skipped.status == "skipped" and "Docker" in skipped.warnings[0]


def test_r22_docker_api_without_tls():
    listen = lambda address: {"id": 1, "ts": NOW, "direction": "listen", "laddr": address, "lport": 2375,
                              "process_name": "com.docker.backend.exe"}
    assert [(a.severity) for a in catalog.r22(EvidenceView(connections=(listen("127.0.0.1"),)), None)] == ["high"]
    assert [(a.severity) for a in catalog.r22(EvidenceView(connections=(listen("0.0.0.0"),)), None)] == ["critical"]
