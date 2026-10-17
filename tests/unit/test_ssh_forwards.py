from __future__ import annotations

from domain.ssh_forwards import forward, host_settings, parse_command, parse_config


def test_forward_specs():
    assert forward("local", "8090:localhost:8090") == {"kind": "local", "bind": None, "listen": 8090, "target": "localhost:8090"}
    assert forward("local", "0.0.0.0:5432:db:5432")["bind"] == "0.0.0.0"
    assert forward("local", "[::1]:8080:[fe80::1]:80") == {"kind": "local", "bind": "::1", "listen": 8080, "target": "fe80::1:80"}
    assert forward("remote", "2201:localhost:22")["listen"] == 2201
    assert forward("remote", "1080") == {"kind": "remote", "bind": None, "listen": 1080, "target": None}
    assert forward("dynamic", "127.0.0.1:1080") == {"kind": "dynamic", "bind": "127.0.0.1", "listen": 1080, "target": None}
    assert forward("local", "/tmp/socket:/remote/socket") is None


def test_command_lines():
    parsed = parse_command(["ssh.exe", "-T", "-D", "51192", "Autotroph-agente", "sh"])
    assert parsed == {"destination": "Autotroph-agente", "port": None,
                      "forwards": [{"kind": "dynamic", "bind": None, "listen": 51192, "target": None}]}
    parsed = parse_command('ssh -p 2222 -L8090:localhost:8090 -R 2201:localhost:22 -o "LocalForward=9000 db:5432" '
                           "-i key dev@vps.example uptime -L 1:2:3")
    assert parsed["destination"] == "vps.example" and parsed["port"] == 2222
    assert [(f["kind"], f["listen"], f["target"]) for f in parsed["forwards"]] == [
        ("local", 8090, "localhost:8090"), ("remote", 2201, "localhost:22"), ("local", 9000, "db:5432")]


def test_config_blocks_and_host_matching():
    blocks = parse_config("""
# comentario
Host vps prod-*
    HostName 187.77.15.126
    Port 2222
    LocalForward 8090 localhost:8090
Host !prod-db prod-*
    DynamicForward 1080
Host *
    HostName ignored.example
    RemoteForward 2201 localhost:22
""")
    vps = host_settings(blocks, "vps")
    assert (vps["hostname"], vps["port"]) == ("187.77.15.126", 2222)     # first value wins, like ssh
    assert [(f["kind"], f["listen"]) for f in vps["forwards"]] == [("local", 8090), ("remote", 2201)]
    assert ("dynamic", 1080) in [(f["kind"], f["listen"]) for f in host_settings(blocks, "prod-web")["forwards"]]
    assert ("dynamic", 1080) not in [(f["kind"], f["listen"]) for f in host_settings(blocks, "prod-db")["forwards"]]
    assert host_settings(blocks, None)["forwards"] == []
