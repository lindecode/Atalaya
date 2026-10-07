"""Shapes connection rows into the network visuals of the GUI (flow diagram, exposure map, timeline).

Pure functions over the `connections` rows, so they can be tested without Streamlit. Every label that
comes from collected data goes through `safe()`: Plotly renders a small HTML subset (<b>, <a href>…) in
labels and hovers, and a process or path name must never become markup.
"""
from __future__ import annotations

import html
import ipaddress
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import plotly.graph_objects as go


SERVICES = {
    20: "FTP", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 67: "DHCP", 68: "DHCP",
    80: "HTTP", 110: "POP3", 123: "NTP", 135: "RPC", 137: "NetBIOS", 138: "NetBIOS", 139: "SMB",
    143: "IMAP", 161: "SNMP", 389: "LDAP", 443: "HTTPS", 445: "SMB", 465: "SMTPS", 587: "SMTP",
    853: "DNS-TLS", 993: "IMAPS", 995: "POP3S", 1433: "SQL Server", 1900: "SSDP", 3306: "MySQL",
    3389: "RDP", 5222: "XMPP", 5353: "mDNS", 5355: "LLMNR", 5432: "PostgreSQL", 5985: "WinRM",
    5986: "WinRM", 8080: "HTTP alt", 8443: "HTTPS alt", 8501: "panel Atalaya", 11434: "Ollama",
}
CLOSING_STATES = {"TIME_WAIT", "CLOSE_WAIT", "FIN_WAIT1", "FIN_WAIT2", "LAST_ACK", "CLOSING", "SYN_SENT", "SYN_RECV"}
SUSPICIOUS_DIRS = ("\\temp\\", "\\downloads\\", "\\appdata\\local\\temp\\", "\\users\\public\\", "\\$recycle.bin\\")

# Shared palette: readable on light and dark backgrounds
COLORS = {
    "inbound": "#F59E0B", "outbound": "#3987E5", "suspicious": "#EF4444", "process": "#9085E9",
    "public": "#199E70", "private": "#D55181", "loopback": "#94A3B8", "local": "#94A3B8", "other": "#64748B",
}
SCOPE_LABELS = {
    "public": "Internet", "private": "Red local / VPN", "loopback": "Este equipo",
    "link-local": "Enlace local", "multicast": "Multidifusión", "unspecified": "Todas las interfaces", "unknown": "Desconocido",
}


def safe(value: object, limit: int = 80) -> str:
    text = "" if value is None else str(value)
    return html.escape(text[:limit] + ("…" if len(text) > limit else ""))


def scope(address: str | None) -> str:
    if not address:
        return "unknown"
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return "unknown"
    if ip.is_unspecified: return "unspecified"
    if ip.is_loopback: return "loopback"
    if ip.is_link_local: return "link-local"
    if ip.is_multicast: return "multicast"
    if ip.is_private: return "private"
    return "public"


def service(port: int | None) -> str:
    return SERVICES.get(port, f"puerto {port}") if port else "?"


def process_label(row: dict) -> str:
    if row.get("process_name"):
        return str(row["process_name"])
    pid = row.get("pid")
    if pid in (0, 4):
        return "Sistema (kernel)"
    return f"PID {pid} (sin permiso)" if pid else "Desconocido"


def is_suspicious(row: dict, suspicious_ports=()) -> bool:
    path = str(row.get("process_path") or "").replace("/", "\\").casefold()
    return (row.get("rport") in suspicious_ports and row.get("direction") == "outbound") or any(part in path for part in SUSPICIOUS_DIRS)


def active_flows(rows: list[dict], include_loopback: bool = False, include_closing: bool = False) -> list[dict]:
    """Inbound/outbound TCP conversations with a remote end, optionally without local-only or closing ones."""
    result = []
    for row in rows:
        if row.get("direction") not in {"inbound", "outbound"} or not row.get("raddr"):
            continue
        if not include_closing and row.get("state") in CLOSING_STATES:
            continue
        if not include_loopback and scope(row["raddr"]) == "loopback":
            continue
        result.append(row)
    return result


def exposure(rows: list[dict]) -> list[dict]:
    """Listening sockets (TCP LISTEN and bound UDP) with how far they are reachable."""
    seen, result = set(), []
    for row in rows:
        listening = row.get("direction") == "listen" or (row.get("proto") == "udp" and not row.get("raddr"))
        if not listening or row.get("lport") is None:
            continue
        key = (row.get("proto"), row.get("laddr"), row.get("lport"), process_label(row))
        if key in seen:
            continue
        seen.add(key)
        reach = scope(row.get("laddr"))
        level = "Toda la red" if reach == "unspecified" else "Solo este equipo" if reach == "loopback" else "Una interfaz (LAN/VPN)"
        result.append({"alcance": level, "proceso": process_label(row), "puerto": int(row["lport"]),
                       "protocolo": str(row.get("proto") or "?").upper(), "servicio": service(row.get("lport")),
                       "direccion": row.get("laddr")})
    return result


@dataclass
class Flow:
    labels: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    x: list[float] = field(default_factory=list)
    hovers: list[str] = field(default_factory=list)
    source: list[int] = field(default_factory=list)
    target: list[int] = field(default_factory=list)
    value: list[int] = field(default_factory=list)
    link_colors: list[str] = field(default_factory=list)
    link_hovers: list[str] = field(default_factory=list)
    inbound: int = 0
    outbound: int = 0


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def build_flow(rows: list[dict], max_remotes: int = 12, suspicious_ports=()) -> Flow:
    """Three columns: remote origins (inbound) → local processes → remote destinations (outbound)."""
    flow = Flow()
    index: dict[tuple, int] = {}

    def node(key: tuple, label: str, color: str, x: float, hover: str) -> int:
        if key not in index:
            index[key] = len(flow.labels)
            flow.labels.append(label); flow.colors.append(color); flow.x.append(x); flow.hovers.append(hover)
        return index[key]

    for direction in ("inbound", "outbound"):
        subset = [row for row in rows if row.get("direction") == direction]
        ranked = Counter(row["raddr"] for row in subset)
        top = {address for address, _ in ranked.most_common(max_remotes)}
        others = len(ranked) - len(top)
        links: dict[tuple, dict] = defaultdict(lambda: {"count": 0, "ports": Counter(), "suspicious": False})
        for row in subset:
            remote = row["raddr"] if row["raddr"] in top else None
            proc = process_label(row)
            link = links[(remote, proc)]
            link["count"] += 1
            link["ports"][row.get("rport") if direction == "outbound" else row.get("lport")] += 1
            link["suspicious"] |= is_suspicious(row, suspicious_ports)
            link["scope"] = scope(row["raddr"])
        for (remote, proc), link in links.items():
            if remote is None:
                remote_label, color, hover = f"Otros ({others} IP)", COLORS["other"], "IP agrupadas fuera del top"
            else:
                remote_label = safe(remote)
                color = COLORS["suspicious"] if link["suspicious"] else COLORS.get(link["scope"], COLORS["other"])
                hover = f"{safe(remote)} · {SCOPE_LABELS.get(link['scope'], link['scope'])}"
            # Keep edge labels inside Plotly's drawing domain. Values too close
            # to 0/1 let IPv6 addresses overflow the Streamlit container.
            x = 0.06 if direction == "inbound" else 0.94
            remote_node = node((direction, remote), remote_label, color, x, hover)
            proc_node = node(("process", proc), safe(proc, 40), COLORS["process"], 0.5, safe(proc, 120))
            ports = ", ".join(f"{service(port)}" + (f" ({port})" if port and port in SERVICES else "")
                              for port, _ in link["ports"].most_common(4))
            if direction == "inbound":
                flow.source.append(remote_node); flow.target.append(proc_node); flow.inbound += link["count"]
                verb = f"entrante a {safe(proc, 40)} · puerto local: {ports}"
            else:
                flow.source.append(proc_node); flow.target.append(remote_node); flow.outbound += link["count"]
                verb = f"saliente de {safe(proc, 40)} · {ports}"
            flow.value.append(link["count"])
            base = COLORS["suspicious"] if link["suspicious"] else COLORS[direction]
            flow.link_colors.append(_rgba(base, 0.75 if link["suspicious"] else 0.42))
            flow.link_hovers.append(f"{link['count']} conexión(es) {verb}" + (" · ⚠ sospechosa" if link["suspicious"] else ""))
    return flow


def flow_figure(flow: Flow, height: int = 560) -> go.Figure:
    height = max(420, min(height, 760))
    figure = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=flow.labels, color=flow.colors, x=flow.x, pad=14, thickness=16,
                  line=dict(width=0), customdata=flow.hovers, hovertemplate="%{customdata}<extra></extra>"),
        link=dict(source=flow.source, target=flow.target, value=flow.value, color=flow.link_colors,
                  customdata=flow.link_hovers, hovertemplate="%{customdata}<extra></extra>"),
    ))
    figure.update_layout(height=height, autosize=True, margin=dict(l=28, r=28, t=44, b=12), font=dict(size=11),
                         paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    for x, text, color in ((0.02, "◀ ORIGEN (entrantes)", COLORS["inbound"]), (0.5, "PROCESOS DE ESTE EQUIPO", COLORS["process"]),
                           (0.98, "DESTINO (salientes) ▶", COLORS["outbound"])):
        figure.add_annotation(x=x, y=1.06, xref="paper", yref="paper", text=f"<b>{text}</b>", showarrow=False,
                              font=dict(color=color, size=11),
                              xanchor="left" if x < 0.1 else "right" if x > 0.9 else "center")
    return figure


def exposure_figure(items: list[dict]) -> go.Figure:
    order = ["Toda la red", "Una interfaz (LAN/VPN)", "Solo este equipo"]
    palette = {"Toda la red": COLORS["suspicious"], "Una interfaz (LAN/VPN)": COLORS["inbound"], "Solo este equipo": COLORS["loopback"]}
    ids, labels, parents, values, colors = [], [], [], [], []
    for level in order:
        group = [item for item in items if item["alcance"] == level]
        if not group: continue
        ids.append(level); labels.append(f"{level} ({len(group)})"); parents.append(""); values.append(len(group)); colors.append(palette[level])
        by_proc = Counter(item["proceso"] for item in group)
        for proc, count in by_proc.items():
            ids.append(f"{level}/{proc}"); labels.append(safe(proc, 40)); parents.append(level); values.append(count)
            colors.append(_rgba(palette[level], 0.55))
            for item in (i for i in group if i["proceso"] == proc):
                ids.append(f"{level}/{proc}/{item['protocolo']}{item['puerto']}")
                labels.append(f"{item['protocolo']} {item['puerto']} · {safe(item['servicio'], 24)}")
                parents.append(f"{level}/{proc}"); values.append(1); colors.append(_rgba(palette[level], 0.3))
    figure = go.Figure(go.Treemap(ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
                                  marker=dict(colors=colors, line=dict(width=1)), hovertemplate="%{label}<extra></extra>",
                                  tiling=dict(pad=3)))
    figure.update_layout(height=420, margin=dict(l=4, r=4, t=4, b=4), paper_bgcolor="rgba(0,0,0,0)")
    return figure


def destinations_figure(rows: list[dict]) -> go.Figure:
    """Outbound conversations by service, then by remote scope."""
    counts = Counter((service(row.get("rport")), SCOPE_LABELS.get(scope(row["raddr"]), "?"))
                     for row in rows if row.get("direction") == "outbound")
    services = Counter()
    for (svc, _), count in counts.items(): services[svc] += count
    ids = [svc for svc in services] + [f"{svc}/{where}" for (svc, where) in counts]
    labels = [safe(svc, 24) for svc in services] + [where for (_, where) in counts]
    parents = ["" for _ in services] + [svc for (svc, _) in counts]
    values = [services[svc] for svc in services] + list(counts.values())
    figure = go.Figure(go.Sunburst(ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
                                   hovertemplate="%{label}: %{value} conexión(es)<extra></extra>", insidetextorientation="radial"))
    figure.update_layout(height=420, margin=dict(l=4, r=4, t=4, b=4), paper_bgcolor="rgba(0,0,0,0)")
    return figure


def timeline_rows(rows: list[dict], include_loopback: bool = False) -> list[dict]:
    """Per collection (run): how many inbound/outbound conversations were open."""
    buckets: dict[tuple, int] = Counter()
    stamp: dict[int, str] = {}
    for row in active_flows(rows, include_loopback):
        buckets[(row["run_id"], row["direction"])] += 1
        stamp.setdefault(row["run_id"], row["ts"])
    names = {"inbound": "Entrantes", "outbound": "Salientes"}
    return [{"ts": stamp[run], "sentido": names[direction], "conexiones": count}
            for (run, direction), count in sorted(buckets.items(), key=lambda item: stamp[item[0][0]])]
