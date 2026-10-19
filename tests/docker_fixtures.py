# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Docker CLI output shaped like the real thing (docker inspect / ps / image ls / network / volume / events JSON)."""
from __future__ import annotations

import json

POSTGRES = {
    "Id": "a1b2c3d4e5f6" + "0" * 52, "Name": "/shop-db-1",
    "Config": {"Image": "postgres:16", "User": "", "Env": ["POSTGRES_PASSWORD=hunter2", "POSTGRES_PASSWORD_FILE=/run/s",
                                                        "PGDATA=/var/lib/postgresql/data", "LANG=en_US.utf8"],
               "Labels": {"com.docker.compose.project": "shop", "com.docker.compose.service": "db"}},
    "State": {"Status": "running", "Running": True, "OOMKilled": False, "ExitCode": 0,
              "StartedAt": "2026-10-14T18:00:00.000000000Z", "Health": {"Status": "healthy"}},
    "RestartCount": 0,
    "HostConfig": {"Privileged": False, "NetworkMode": "shop_default", "CapAdd": None,
                   "RestartPolicy": {"Name": "unless-stopped"}},
    "Mounts": [{"Type": "volume", "Name": "shop_pgdata", "Source": "/var/lib/docker/volumes/shop_pgdata/_data",
                "Destination": "/var/lib/postgresql/data", "RW": True}],
    "NetworkSettings": {"Ports": {"5432/tcp": [{"HostIp": "0.0.0.0", "HostPort": "5432"},
                                               {"HostIp": "::", "HostPort": "5432"}]},
                        "Networks": {"shop_default": {"IPAddress": "172.18.0.2"}}},
}
API = {
    "Id": "f6e5d4c3b2a1" + "0" * 52, "Name": "/shop-api-1",
    "Config": {"Image": "shop-api:latest", "User": "app", "Env": ["NODE_ENV=production"],
               "Labels": {"com.docker.compose.project": "shop", "com.docker.compose.service": "api"}},
    "State": {"Status": "running", "Running": True, "OOMKilled": False, "ExitCode": 0,
              "StartedAt": "2026-10-14T18:01:00Z"},
    "RestartCount": 4,
    "HostConfig": {"Privileged": False, "NetworkMode": "shop_default", "CapAdd": None},
    "Mounts": [{"Type": "bind", "Source": "C:\\Users\\dev\\shop", "Destination": "/app", "RW": True}],
    "NetworkSettings": {"Ports": {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3000"}], "9229/tcp": None},
                        "Networks": {"shop_default": {"IPAddress": "172.18.0.3"}}},
}
PORTAINER = {
    "Id": "0123456789ab" + "0" * 52, "Name": "/portainer",
    "Config": {"Image": "portainer/portainer-ce:2.21", "Env": [], "Labels": {}},
    "State": {"Status": "exited", "Running": False, "OOMKilled": True, "ExitCode": 137, "StartedAt": "2026-10-13T08:00:00Z"},
    "RestartCount": 0,
    "HostConfig": {"Privileged": True, "NetworkMode": "host", "CapAdd": ["CAP_SYS_ADMIN"]},
    "Mounts": [{"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock", "RW": True},
               {"Type": "bind", "Source": "C:\\", "Destination": "/host", "RW": False}],
    "NetworkSettings": {"Ports": {}, "Networks": {"host": {"IPAddress": ""}}},
}
CONTAINERS = [POSTGRES, API, PORTAINER]
STATS = {"a1b2c3d4e5f6": {"ID": "a1b2c3d4e5f6", "CPUPerc": "0.35%", "MemUsage": "48MiB / 7.6GiB"}}
IMAGES = [
    {"ID": "sha256:1111", "Repository": "postgres", "Tag": "16", "Size": "432MB", "CreatedAt": "2026-09-01 10:00:00 +0000 UTC",
     "Containers": "1"},
    {"ID": "sha256:2222", "Repository": "shop-api", "Tag": "latest", "Size": "210MB",
     "CreatedAt": "2026-10-14 17:55:00 +0000 UTC", "Containers": "1"},
    {"ID": "sha256:3333", "Repository": "<none>", "Tag": "<none>", "Size": "205MB",
     "CreatedAt": "2026-10-10 09:00:00 +0000 UTC", "Containers": "0"},
]
NETWORKS = [
    {"Name": "shop_default", "Id": "n1" * 32, "Driver": "bridge", "Scope": "local", "Internal": False,
     "IPAM": {"Config": [{"Subnet": "172.18.0.0/16", "Gateway": "172.18.0.1"}]},
     "Containers": {POSTGRES["Id"]: {"Name": "shop-db-1", "IPv4Address": "172.18.0.2/16"},
                    API["Id"]: {"Name": "shop-api-1", "IPv4Address": "172.18.0.3/16"}}},
    {"Name": "bridge", "Id": "n2" * 32, "Driver": "bridge", "Scope": "local", "Internal": False,
     "IPAM": {"Config": [{"Subnet": "172.17.0.0/16", "Gateway": "172.17.0.1"}]}, "Containers": {}},
    {"Name": "host", "Id": "n3" * 32, "Driver": "host", "Scope": "local", "Internal": False, "IPAM": {"Config": []},
     "Containers": {}},
]
VOLUMES = [
    {"Name": "shop_pgdata", "Driver": "local", "Mountpoint": "/var/lib/docker/volumes/shop_pgdata/_data",
     "CreatedAt": "2026-09-01T10:00:00Z", "Labels": {"com.docker.compose.project": "shop"}},
    {"Name": "d" * 64, "Driver": "local", "Mountpoint": "/var/lib/docker/volumes/x/_data",
     "CreatedAt": "2026-08-01T10:00:00Z", "Labels": None},
]
EVENTS = [
    {"Type": "container", "Action": "die", "time": 1000, "Actor": {"ID": "f6e5", "Attributes": {"name": "shop-api-1", "image": "shop-api:latest", "exitCode": "1"}}},
    {"Type": "container", "Action": "die", "time": 1060, "Actor": {"ID": "f6e5", "Attributes": {"name": "shop-api-1", "exitCode": "1"}}},
    {"Type": "container", "Action": "die", "time": 1120, "Actor": {"ID": "f6e5", "Attributes": {"name": "shop-api-1", "exitCode": "1"}}},
    {"Type": "container", "Action": "die", "time": 1180, "Actor": {"ID": "f6e5", "Attributes": {"name": "shop-api-1", "exitCode": "1"}}},
    {"Type": "container", "Action": "oom", "time": 1200, "Actor": {"ID": "0123", "Attributes": {"name": "portainer"}}},
    {"Type": "container", "Action": "health_status: unhealthy", "time": 1300,
     "Actor": {"ID": "a1b2", "Attributes": {"name": "shop-db-1"}}},
    {"Type": "container", "Action": "start", "time": 1400, "Actor": {"ID": "a1b2", "Attributes": {"name": "shop-db-1"}}},
]


class FakeRunner:
    """Stands in for subprocess.run: answers the read-only commands DockerCLI issues."""

    def __init__(self, running: bool = True):
        self.running, self.calls = running, []

    def __call__(self, command, **kwargs):
        args = tuple(command[1:])
        self.calls.append(args)
        out = lambda text: type("Done", (), {"returncode": 0, "stdout": text, "stderr": ""})()
        if not self.running:
            return type("Done", (), {"returncode": 1, "stdout": "", "stderr":
                                     "failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine"})()
        lines = lambda rows: "\n".join(json.dumps(row) for row in rows)
        if args[0] == "version":
            return out(json.dumps({"Client": {"Version": "29.8.2", "Context": "desktop-linux"},
                                   "Server": {"Version": "29.8.2", "Os": "linux"}}))
        if args[0] == "ps":
            return out(lines({"ID": c["Id"], "Names": c["Name"][1:]} for c in CONTAINERS))
        if args[0] == "inspect":
            ids = set(args[args.index("--") + 1:])
            return out(json.dumps([c for c in CONTAINERS if c["Id"] in ids]))
        if args[0] == "stats":
            return out(lines(STATS.values()))
        if args[:2] == ("image", "ls"):
            return out(lines(IMAGES))
        if args[:2] == ("network", "ls"):
            return out(lines({"ID": n["Id"], "Name": n["Name"]} for n in NETWORKS))
        if args[:2] == ("network", "inspect"):
            return out(json.dumps(NETWORKS))
        if args[:2] == ("volume", "ls"):
            return out(lines({"Name": v["Name"]} for v in VOLUMES))
        if args[:2] == ("volume", "inspect"):
            return out(json.dumps(VOLUMES))
        if args[0] == "events":
            return out(lines(EVENTS))
        raise AssertionError(f"Comando inesperado: {args}")
