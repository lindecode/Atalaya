from __future__ import annotations

from datetime import datetime, timedelta, timezone

from application import dev_view, docker_view
from application.docker_watch import DockerWatcher
from infrastructure.docker.cli import DockerCLI
from infrastructure.docker.inventory import inventory
from tests.docker_fixtures import EVENTS, FakeRunner
from tests.unit.test_dev_view import SNAPSHOT

INVENTORY = inventory(DockerCLI("docker", FakeRunner()))


def test_inventory_and_summary():
    assert INVENTORY["available"] and INVENTORY["version"]["server"] == "29.8.2"
    assert docker_view.summary(INVENTORY) == {"running": 2, "total": 3, "exposed": 1, "at_risk": 2, "unhealthy": 1,
                                              "dangling_images": 1, "unused_volumes": 1}
    off = inventory(DockerCLI("docker", FakeRunner(running=False)))
    assert off["available"] is False and "dockerDesktopLinuxEngine" in off["error"]


def test_projects_networks_volumes_mounts_and_images():
    groups = docker_view.by_project(INVENTORY["containers"])
    assert [(name, [c["name"] for c in rows]) for name, rows in groups] == [
        ("shop", ["shop-api-1", "shop-db-1"]), (None, ["portainer"])]
    networks = {row["name"]: row for row in docker_view.network_rows(INVENTORY)}
    assert [m["name"] for m in networks["shop_default"]["containers"]] == ["shop-db-1", "shop-api-1"]
    assert networks["shop_default"]["subnet"] == "172.18.0.0/16"
    volumes = docker_view.volume_rows(INVENTORY)
    assert (volumes[0]["name"], volumes[0]["used_by"]) == ("shop_pgdata", ["shop-db-1"])
    assert volumes[1]["anonymous"] and volumes[1]["used_by"] == []
    mounts = {m["source"]: m for m in docker_view.bind_mounts(INVENTORY)}
    assert mounts["/var/run/docker.sock"]["sensitive"] and not mounts["C:\\Users\\dev\\shop"]["sensitive"]
    images = {row["image"]: row for row in docker_view.image_rows(INVENTORY)}
    assert images["postgres:16"]["containers"] == ["shop-db-1"] and images["<none>:<none>"]["dangling"]
    assert images["shop-api:latest"]["latest"] and images["postgres:16"]["age_days"] >= 0


def test_network_graph_places_containers_around_their_networks():
    graph = docker_view.network_graph(INVENTORY)
    ids = {node["id"]: node for node in graph["nodes"]}
    assert {"host", "n:shop_default", "c:shop-db-1", "c:shop-api-1"} <= set(ids)
    assert "n:bridge" not in ids                                    # empty networks stay in the table only
    assert ids["c:shop-db-1"]["ring"] == "#ef4444"                  # high risk: 5432 published to the network


def test_chat_tool_and_unavailable_docker():
    result = docker_view.tool_result(INVENTORY, {"only_risky": True})
    assert [row["id"] for row in result["rows"]] == ["shop-db-1", "portainer"]
    assert "-p 127.0.0.1:5432:5432" in " ".join(result["rows"][0]["risks"])
    assert docker_view.tool_result({"available": False, "error": "apagado"}, {})["summary"]["docker"] == "no disponible"


def test_main_map_names_the_container_behind_docker_desktop():
    snapshot = {**SNAPSHOT, "connections": SNAPSHOT["connections"] + [
        {"direction": "listen", "laddr": "0.0.0.0", "lport": 5432, "pid": 40, "process_name": "com.docker.backend.exe"}]}
    from domain import docker
    rows = {row["port"]: row for row in dev_view.servers(snapshot, port_names=docker.port_names(INVENTORY["containers"]))}
    assert rows[5432]["target"] == "shop-db-1 (postgres:16)"


def test_docker_watch_notifies_problems_once_and_survives_a_stopped_engine():
    start = datetime.fromtimestamp(900, timezone.utc)
    clock = {"now": start, "mono": 0.0}
    runner = FakeRunner()
    watcher = DockerWatcher(DockerCLI("docker", runner), lambda: "2026-10-14T12:00:00+00:00",
                            clock=lambda: clock["now"], monotonic=lambda: clock["mono"])
    assert watcher.poll() == []                                     # first look: only the starting point
    clock["now"] = start + timedelta(seconds=600)
    notices = watcher.poll()
    assert [(n.kind, n.process_name, n.detail.split(":")[0]) for n in notices] == [
        ("docker", "shop-api-1", "restart_loop"), ("docker", "portainer", "oom"), ("docker", "shop-db-1", "unhealthy")]
    assert notices[0].title() == "Contenedor con problemas" and "reinicios" in notices[0].message()
    assert watcher.port_names[5432] == "shop-db-1 (postgres:16)"
    clock["now"] += timedelta(seconds=30)
    assert watcher.poll() == []                                     # the same problems are muted for an hour
    runner.running = False
    clock["now"] += timedelta(seconds=30)
    assert watcher.poll() == [] and watcher.port_names == {}
    assert len(EVENTS) == 7


def test_recommendations_rank_debug_docker_and_ssh_with_their_fixes():
    from application import ssh_view
    from tests.unit.test_ssh_view import HISTORY, SNAPSHOT as SSH_SNAPSHOT
    items = dev_view.recommendations(dev_view.servers(SNAPSHOT), INVENTORY, ssh_view.model(HISTORY, SSH_SNAPSHOT))
    severities = [item["severity"] for item in items]
    assert severities == sorted(severities, key=dev_view.SEVERITY_ORDER.get)        # most severe first
    texts = " | ".join(item["text"][0] for item in items)
    assert "Inspector de Node.js" in texts and ":8080 (java.exe) escucha en todas las redes" in texts
    assert "Docker shop-db-1" in texts and "SSH 10.0.0.5:22" in texts
    java = next(item for item in items if ":8080" in item["text"][0])
    assert java["fix"].startswith("server.address=127.0.0.1")
    assert any(item["fix"] == "-p 127.0.0.1:5432:5432" for item in items)


def test_development_digest_for_the_llm(tmp_path):
    from dataclasses import replace
    from infrastructure.sqlite.connection import connect
    from infrastructure.sqlite.repositories import SQLiteRepository
    from infrastructure.sqlite.section_summaries import SQLiteSectionDigests
    from settings import Settings
    settings = replace(Settings(), database_path=tmp_path / "d.db")
    SQLiteRepository(settings).initialize()
    now = datetime.now(timezone.utc).isoformat()
    with connect(settings.database_path) as db:
        for lport, process, laddr in ((8080, "java.exe", "0.0.0.0"), (135, None, "0.0.0.0"), (6850, "Lights.exe", "127.0.0.1")):
            db.execute("INSERT INTO connections(ts, source, direction, laddr, lport, process_name) VALUES (?,?,?,?,?,?)",
                       (now, "psutil", "listen", laddr, lport, process))
    digest = SQLiteSectionDigests(settings).digest("desarrollo", 24, now)
    assert digest["datos"]["servidores_expuestos_a_la_red"] == ["java.exe (Java) en el puerto 8080 acepta conexiones de todas las redes (0.0.0.0/::)"]
    assert digest["datos"]["servidores_solo_de_este_equipo"]["cantidad"] == 0 and digest["ventana_anterior"] == {"clientes_entrantes": 0}  # RPC and local helpers left out
    from application.section_summaries import SECTIONS
    assert SECTIONS["desarrollo"] == "Desarrollo"


def test_development_digest_reads_long_docker_observations(tmp_path):
    """Regression: the digest's 120-character text cut used to break the stored container JSON."""
    from dataclasses import replace
    from domain.models import CollectionRequest
    from infrastructure.docker.collector import DockerCollector
    from infrastructure.sqlite.repositories import SQLiteRepository
    from infrastructure.sqlite.section_summaries import SQLiteSectionDigests
    from settings import Settings
    settings = replace(Settings(), database_path=tmp_path / "d.db")
    repository = SQLiteRepository(settings)
    repository.initialize()
    now = datetime.now(timezone.utc).isoformat()
    result = DockerCollector(DockerCLI("docker", FakeRunner())).collect(CollectionRequest(now))
    repository.save_collection(repository.start_run("collect", now, False), result, now)
    data = SQLiteSectionDigests(settings).digest("desarrollo", 24, now)["datos"]
    assert any(line.startswith("Contenedor shop-db-1 (postgres:16) running") and "published" in line
               for line in data["contenedores_docker"])
    assert "Contenedor portainer: capabilities, docker_socket, host_network, host_root, privileged" in data["puntos_a_revisar"]
