from __future__ import annotations

from interfaces.gui import network


def conn(direction, raddr, rport=443, lport=50000, state="ESTABLISHED", name="app.exe", path=r"C:\Program Files\app.exe", **extra):
    return {"direction": direction, "raddr": raddr, "rport": rport, "laddr": "192.168.1.5", "lport": lport, "state": state,
            "process_name": name, "process_path": path, "pid": 100, "proto": "tcp", "run_id": 1, "ts": "2026-10-02T10:00:00+00:00", **extra}


def test_scope_and_service_classification():
    assert network.scope("8.8.8.8") == "public"
    assert network.scope("192.168.1.10") == "private"
    assert network.scope("127.0.0.1") == "loopback"
    assert network.scope("0.0.0.0") == "unspecified"
    assert network.scope("fe80::1%12") == "link-local"
    assert network.scope(None) == "unknown"
    assert network.service(443) == "HTTPS" and network.service(3389) == "RDP" and network.service(40000) == "puerto 40000"


def test_active_flows_hide_loopback_and_closing_by_default():
    rows = [conn("outbound", "8.8.8.8"), conn("outbound", "127.0.0.1"), conn("outbound", "1.1.1.1", state="TIME_WAIT"),
            conn("listen", None), {"direction": None, "proto": "udp", "raddr": None}]
    assert [r["raddr"] for r in network.active_flows(rows)] == ["8.8.8.8"]
    assert len(network.active_flows(rows, include_loopback=True, include_closing=True)) == 3


def test_flow_has_three_columns_and_groups_remotes_beyond_the_top():
    rows = [conn("inbound", "203.0.113.7", lport=3389, name="svchost.exe")]
    rows += [conn("outbound", f"93.184.216.{i}") for i in range(5)]
    flow = network.build_flow(rows, max_remotes=2)

    assert flow.inbound == 1 and flow.outbound == 5
    assert any(label.startswith("Otros (3 IP)") for label in flow.labels)
    xs = dict(zip(flow.labels, flow.x))
    assert xs["203.0.113.7"] < xs["svchost.exe"] < xs["93.184.216.0"]  # origin -> process -> destination
    assert any("RDP" in hover for hover in flow.link_hovers)


def test_suspicious_links_are_red():
    rows = [conn("outbound", "198.51.100.9", rport=4444), conn("outbound", "8.8.8.8", path=r"C:\Users\me\Downloads\x.exe")]
    flow = network.build_flow(rows, suspicious_ports=(4444,))
    assert all(color.startswith("rgba(239,68,68") for color in flow.link_colors)
    assert sum("sospechosa" in hover for hover in flow.link_hovers) == 2


def test_collected_names_cannot_inject_markup_into_the_chart():
    payload = '<a href="http://evil.example">x</a>.exe'
    flow = network.build_flow([conn("outbound", "8.8.8.8", name=payload)])
    rendered = " ".join(flow.labels + flow.hovers + flow.link_hovers)
    assert "<a" not in rendered and "&lt;a href=" in rendered


def test_exposure_levels_and_dedup():
    rows = [conn("listen", None, lport=445, name="System", laddr="0.0.0.0"),
            conn("listen", None, lport=445, name="System", laddr="0.0.0.0"),
            conn("listen", None, lport=11434, name="ollama.exe", laddr="127.0.0.1"),
            {"direction": None, "proto": "udp", "raddr": None, "laddr": "192.168.1.5", "lport": 5353, "process_name": "x.exe"}]
    levels = sorted(item["alcance"] for item in network.exposure(rows))
    assert levels == ["Solo este equipo", "Toda la red", "Una interfaz (LAN/VPN)"]


def test_timeline_counts_per_collection():
    rows = [conn("outbound", "8.8.8.8", run_id=1), conn("outbound", "1.1.1.1", run_id=1),
            conn("inbound", "203.0.113.7", run_id=2, ts="2026-10-02T11:00:00+00:00")]
    points = network.timeline_rows(rows)
    assert {(p["sentido"], p["conexiones"]) for p in points} == {("Salientes", 2), ("Entrantes", 1)}


def test_figures_build_without_errors():
    rows = [conn("outbound", "8.8.8.8"), conn("inbound", "203.0.113.7"), conn("listen", None, laddr="0.0.0.0")]
    flow = network.build_flow(network.active_flows(rows))
    figure = network.flow_figure(flow, height=2000)
    assert figure.data
    assert figure.layout.height == 760
    assert min(flow.x) >= 0.06 and max(flow.x) <= 0.94
    assert network.exposure_figure(network.exposure(rows)).data
    assert network.destinations_figure(rows).data
