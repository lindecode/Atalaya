from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

from domain.models import CollectionResult, IpName, NetworkConnection
from infrastructure.sqlite.queries import SQLiteQueryRepository
from infrastructure.sqlite.repositories import SQLiteRepository
from interfaces.gui import network
from settings import Settings

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(timezone.utc)


def _seed(tmp_path, monkeypatch=None):
    database = tmp_path / "conn.db"
    if monkeypatch:
        monkeypatch.setenv("ATALAYA_DB", str(database))
        monkeypatch.setenv("ATALAYA_REPORTS", str(tmp_path / "reports"))
    settings = replace(Settings(), database_path=database, reports_dir=tmp_path / "r")
    repository = SQLiteRepository(settings)
    repository.initialize()
    run = repository.start_run("collect", NOW.isoformat(), False)
    ts = NOW.isoformat()
    rows = (
        NetworkConnection(ts, "psutil", "tcp", "listen", "0.0.0.0", 3389, None, None, "LISTEN", 1, "svchost.exe", None, None),
        NetworkConnection(ts, "psutil", "tcp", "inbound", "192.168.1.5", 3389, "8.8.4.4", 50000, "ESTABLISHED", 1, "svchost.exe", None, None),
        NetworkConnection(ts, "psutil", "tcp", "listen", "127.0.0.1", 9000, None, None, "LISTEN", 2, "local.exe", None, None),
        NetworkConnection(ts, "psutil", "tcp", "outbound", "192.168.1.5", 50001, "93.184.216.34", 443, "ESTABLISHED", 3, "msedge.exe", None, None),
    )
    repository.save_collection(run, CollectionResult("psutil_connections", "connections", rows, "ok"), ts)
    repository.save_collection(run, CollectionResult("ip_names", "ip_names", (IpName(ts, "93.184.216.34", "example.com", "dns_cache"),), "ok"), ts)
    return settings, repository


def test_best_name_prefers_the_persons_label_then_recent_dns():
    entry = {"label": None, "names": [{"name": "rev.example", "source": "reverse_dns", "last_seen": "2"},
                                      {"name": "www.example", "source": "dns_cache", "last_seen": "1"}]}
    assert network.best_name(entry) == ("www.example", "dns_cache")
    assert network.best_name({**entry, "label": "Mi servidor"}) == ("Mi servidor", "label")
    assert network.best_name(None) == (None, None)


def test_server_rows_flag_internet_clients_on_network_wide_ports(tmp_path):
    settings, _ = _seed(tmp_path)
    rows = network.server_rows(SQLiteQueryRepository(settings).servers((NOW - timedelta(hours=1)).isoformat()))
    first = rows[0]
    assert (first["puerto"], first["alcance"], first["clientes_internet"], first["atencion"]) == (3389, "Toda la red", 1, True)
    local = next(row for row in rows if row["puerto"] == 9000)
    assert local["alcance"] == "Solo este equipo" and not local["atencion"]


def test_connections_page_has_servers_and_ips_tabs_with_names(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    app = AppTest.from_file(ROOT / "interfaces/gui/views/11_Conexiones.py", default_timeout=30).run()
    assert not app.exception
    labels = [tab.label for tab in app.tabs]
    assert any("Servidores" in label for label in labels) and any("IPs" in label for label in labels)
    assert not any("Exposición" in label for label in labels)
    servers = app.dataframe(key="table-servers").value
    assert list(servers["Puerto"]) == [3389]  # local-only servers are hidden by default
    assert "Clientes de Internet" in servers["Atención"].iloc[0]
    directory = app.dataframe(key="table-ip-directory").value
    assert directory.set_index("IP").loc["93.184.216.34", "Nombre"] == "example.com"


def test_a_label_saved_from_the_ip_profile_names_the_ip_everywhere(tmp_path, monkeypatch):
    settings, _ = _seed(tmp_path, monkeypatch)
    app = AppTest.from_file(ROOT / "interfaces/gui/views/11_Conexiones.py", default_timeout=30)
    app.query_params["ip"] = "8.8.4.4"
    app.run()
    app.text_input(key="label-filter-8.8.4.4").set_value("Oficina").run()
    app.button(key="label-save-filter-8.8.4.4").click().run()
    assert not app.exception
    assert SQLiteQueryRepository(settings).ip_names(["8.8.4.4"])["8.8.4.4"]["label"] == "Oficina"
