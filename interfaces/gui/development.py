"""Desarrollo: the servers this computer runs, who reaches them, the languages behind them and network notices.

Servers and processes are read live (psutil) so the page reflects what runs now; notices come from the tray's
network watch. Collected text (process names, command lines, IPs) is shown as data: tables, code blocks or
escaped labels, never as Markdown or HTML.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

from application import dev_view
from domain import dev
from interfaces.gui.common import context
from interfaces.gui.components import chart, empty, hero, legend, plain_label, table
from interfaces.gui.node_map import node_map
from interfaces.gui.table_formatting import local_series, to_local_datetime

NOTICE_KINDS = {"client": ("Conexión", "Connection"), "ping": ("Ping", "Ping"), "scan": ("Escaneo", "Scan"),
                "exposed": ("Servidor expuesto", "Exposed server"), "docker": ("Contenedor", "Container")}


@st.cache_data(ttl=5, show_spinner=False)
def _snapshot() -> dict:
    from infrastructure.windows.dev_inventory import snapshot
    return snapshot()


@st.cache_data(ttl=300, show_spinner=False)
def _drops_detectable(firewall_log: str) -> bool:
    from pathlib import Path

    from infrastructure.windows.live_network import drops_detectable
    return drops_detectable(Path(firewall_log))


def _docker_names() -> dict[int, str]:
    from domain import docker
    from interfaces.gui.docker_tab import _inventory
    data = _inventory()
    return docker.port_names(data.get("containers", [])) if data.get("available") else {}


def _notices(settings, since: str) -> list[dict]:
    from infrastructure.sqlite.network_notices import SQLiteNetworkNotices
    try:
        return SQLiteNetworkNotices(settings).recent(since)
    except Exception:  # the table appears with the migration; an old database simply has no notices yet
        return []


def _uptime(started: str | None, lang: str) -> str:
    if not started:
        return "—"
    delta = datetime.now(timezone.utc) - datetime.fromisoformat(started)
    hours, minutes = int(delta.total_seconds() // 3600), int(delta.total_seconds() % 3600 // 60)
    if hours >= 48:
        return f"{hours // 24} d" if lang == "en" else f"{hours // 24} días"
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def development_page():
    settings, _, _, since = context()
    lang = st.session_state.get("language") or "es"
    tr = lambda es, en: en if lang == "en" else es
    hero("🧑‍💻 Desarrollo", "Servidores de este equipo, quién se conecta a ellos, en qué lenguaje corren y los avisos de red.",
         page_key="development", lang=lang)

    controls = st.columns([2, 2, 2, 3], vertical_alignment="bottom")
    live = controls[0].toggle(tr("Actualización automática", "Auto-refresh"), value=True, key="dev-live")
    include_all = controls[1].toggle(tr("Todos los servidores", "All servers"), value=False, key="dev-all",
                                     help=tr("Incluye ayudantes locales de programas comunes (plugins del editor, "
                                             "utilidades del fabricante…).", "Includes local helpers of ordinary "
                                             "programs (editor plugins, vendor utilities…)."))
    local_clients = controls[2].toggle(tr("Clientes de este equipo", "Clients from this computer"), value=False,
                                       key="dev-local", help=tr("Muestra en el mapa las conexiones desde localhost.",
                                                                "Shows localhost connections on the map."))
    controls[3].caption(tr("Servidores y procesos: en vivo. Avisos: ventana temporal de la barra lateral.",
                           "Servers and processes: live. Notices: sidebar time window."))

    if not _drops_detectable(str(settings.firewall_log_path)):
        st.warning(tr("Los pings y escaneos no se detectan: falta la auditoría de paquetes descartados. Vaya a Ajustes → "
                      "Permisos ampliados → Configurar permisos (una vez, pide administrador).",
                      "Pings and scans are not detected: the dropped-packet audit is missing. Go to Settings → Extended "
                      "permissions → Configure permissions (once, asks for administrator)."), icon=":material/lock:")

    @st.fragment(run_every="10s" if live else None)
    def body():
        try:
            snapshot = _snapshot()
        except Exception as exc:
            st.error(tr(f"No se pudo leer el estado de la red: {exc}", f"Could not read the network state: {exc}"))
            return
        rows = dev_view.servers(snapshot, include_all=include_all, port_names=_docker_names())
        notices = _notices(settings, since)
        _kpis(rows, notices, tr)
        exposed_debug = [row for row in rows if row["debug"] and row["scope"] != dev.SCOPE_LOCAL]
        for row in exposed_debug:
            st.error(tr(f"Puerto de depuración expuesto: {row['debug']} en :{row['port']} ({plain_label(row['process'])}). "
                        "Quien lo alcance puede ejecutar código; hágalo escuchar solo en 127.0.0.1.",
                        f"Exposed debug port: {row['debug']} on :{row['port']} ({plain_label(row['process'])}). "
                        "Whoever reaches it can run code; bind it to 127.0.0.1."), icon=":material/bug_report:")
        map_tab, servers_tab, docker_tab_, ssh_tab_, timeline_tab, languages_tab, port_tab, notices_tab = st.tabs([
            ":material/hub: " + tr("Mapa", "Map"), ":material/dns: " + tr("Servidores", "Servers"),
            ":material/deployed_code: Docker", ":material/vpn_key: SSH",
            ":material/timeline: " + tr("Línea de tiempo", "Timeline"),
            ":material/code: " + tr("Lenguajes", "Languages"),
            ":material/search: " + tr("¿Quién usa el puerto?", "Who uses the port?"),
            ":material/notifications: " + tr("Avisos de red", "Network notices")])
        with map_tab:
            _map(rows, notices, local_clients, lang, tr)
        with servers_tab:
            _servers(rows, lang, tr)
        with docker_tab_:
            from interfaces.gui.docker_tab import docker_tab
            docker_tab(settings, lang, tr)
        with ssh_tab_:
            from interfaces.gui.ssh_tab import ssh_tab
            ssh_tab(settings, snapshot, since, lang, tr)
        with timeline_tab:
            _timeline(str(settings.database_path), since, include_all, lang, tr)
        with languages_tab:
            _languages(snapshot, lang, tr)
        with port_tab:
            _port_lookup(snapshot, lang, tr)
        with notices_tab:
            _notice_history(notices, lang, tr)

    body()


def _kpis(rows, notices, tr):
    a, b, c, d, e = st.columns(5)
    a.metric(tr("Servidores", "Servers"), len(rows))
    b.metric(tr("Expuestos a la red", "Exposed to the network"), sum(row["scope"] != dev.SCOPE_LOCAL for row in rows),
             help=tr("Escuchan en la red local o en todas las interfaces (0.0.0.0 / ::).",
                     "Listen on the local network or on every interface (0.0.0.0 / ::)."))
    c.metric(tr("Depuración expuesta", "Exposed debug ports"),
             sum(bool(row["debug"]) and row["scope"] != dev.SCOPE_LOCAL for row in rows))
    d.metric(tr("Clientes externos ahora", "External clients now"),
             sum(client["origin"] in {"lan", "internet"} for row in rows for client in row["clients"]))
    e.metric(tr("Avisos de red", "Network notices"), len(notices))


def _map(rows, notices, local_clients, lang, tr):
    if not rows:
        empty(tr("No hay servidores de desarrollo en marcha ni puertos expuestos.",
                 "No development servers running and no exposed ports."))
        return
    graph = dev_view.graph(rows, notices, lang=lang, include_local_clients=local_clients)
    legend([(tr("Solo este equipo", "This computer only"), dev_view.SCOPE_COLORS[dev.SCOPE_LOCAL]),
            (tr("Red local", "Local network"), dev_view.SCOPE_COLORS[dev.SCOPE_LAN]),
            (tr("Todas las redes", "Every network"), dev_view.SCOPE_COLORS[dev.SCOPE_ALL]),
            (tr("Cliente LAN", "LAN client"), dev_view.ORIGIN_COLORS["lan"]),
            (tr("Cliente de Internet", "Internet client"), dev_view.ORIGIN_COLORS["internet"])])
    st.caption(tr("Anillo del servidor = alcance; color = lenguaje. Línea discontinua: cliente que ya se desconectó "
                  "(de los avisos). Haga clic en un nodo para ver su detalle.",
                  "Server ring = reach; fill = language. Dashed line: client already gone (from notices). "
                  "Click a node for its detail."))
    left, right = st.columns([2, 1])
    with left:
        selected = node_map(graph, key="dev-map", selected=st.session_state.get("dev-map-selected"),
                            label=tr("Mapa de servidores y clientes", "Server and client map"))
    st.session_state["dev-map-selected"] = selected
    with right:
        _detail(selected, rows, notices, lang, tr)


def _detail(selected, rows, notices, lang, tr):
    server = next((row for row in rows if row["id"] == selected), None)
    if server:
        with st.container(border=True):
            st.markdown(f"**:{server['port']} · {plain_label(server['language'])}**")
            st.text(f"{server['process']} (PID {server['pid']})")
            reach = dev.SCOPE_LABELS[server["scope"]][lang == "en"]
            # Inline code shows its content literally: only a backtick could break out of it
            st.markdown(tr("Alcance: ", "Reach: ") + reach + " · " + ", ".join(
                f"`{str(address).replace('`', '')}`" for address in server["addresses"]))
            if server["debug"]:
                st.warning(server["debug"], icon=":material/bug_report:")
            st.caption(tr("Activo desde hace ", "Up for ") + _uptime(server["started"], lang)
                       + (f" · {server['memory_mb']} MB" if server.get("memory_mb") else ""))
            if server.get("target"):
                st.text(tr("Aplicación Java: ", "Java application: ") + server["target"])
            if server.get("command"):
                st.code(server["command"], language=None, wrap_lines=True)
            clients = [{tr("IP", "IP"): client["ip"], tr("Red", "Network"): client["origin"] or "?",
                        tr("Puerto remoto", "Remote port"): client["port"]} for client in server["clients"]]
            if clients:
                st.dataframe(pd.DataFrame(clients), hide_index=True, width="stretch")
            else:
                st.caption(tr("Sin clientes conectados ahora.", "No clients connected now."))
        return
    if selected and selected.startswith("c:"):
        ip = selected[2:]
        with st.container(border=True):
            st.markdown(f"**`{ip.replace('`', '')}`**")
            origin = dev.origin(ip)
            st.caption({"lan": tr("Red local", "Local network"), "internet": "Internet",
                        "local": tr("Este equipo", "This computer")}.get(origin or "", "?"))
            served = [f":{row['port']} ({row['process']})" for row in rows
                      if any(client["ip"] == ip for client in row["clients"])]
            if served:
                st.text(tr("Conectado ahora a ", "Connected now to ") + ", ".join(served))
            history = [notice for notice in notices if notice.get("remote_ip") == ip]
            if history:
                st.dataframe(pd.DataFrame([{tr("Fecha", "Date"): to_local_datetime(n["ts"]),
                                            tr("Tipo", "Kind"): NOTICE_KINDS.get(n["kind"], (n["kind"],) * 2)[lang == "en"],
                                            tr("Puerto", "Port"): n.get("lport")} for n in history]),
                             hide_index=True, width="stretch")
            from interfaces.gui.components import page_link
            page_link("views/10_Buscar.py", tr(f"Buscar «{plain_label(ip)}»", f"Search «{plain_label(ip)}»"),
                      ":material/search:", query_params={"q": ip})
        return
    st.info(tr("Haga clic en un servidor o en un cliente del mapa.", "Click a server or a client on the map."),
            icon=":material/touch_app:")


def _servers(rows, lang, tr):
    if not rows:
        empty(tr("No hay servidores que mostrar.", "No servers to show."))
        return
    for start in range(0, len(rows), 3):
        for column, row in zip(st.columns(3), rows[start:start + 3]):
            with column.container(border=True):
                badge = {dev.SCOPE_LOCAL: ":green-badge", dev.SCOPE_LAN: ":orange-badge",
                         dev.SCOPE_ALL: ":red-badge"}[row["scope"]]
                st.markdown(f"**:{row['port']}** · {plain_label(row['language'])} "
                            f"{badge}[{dev.SCOPE_LABELS[row['scope']][lang == 'en']}]")
                st.text(row["target"] or row["process"])
                external = sum(client["origin"] in {"lan", "internet"} for client in row["clients"])
                st.caption(tr(f"{len(row['clients'])} clientes ({external} externos) · activo {_uptime(row['started'], lang)}",
                              f"{len(row['clients'])} clients ({external} external) · up {_uptime(row['started'], lang)}"))
                if row["debug"]:
                    st.markdown(":red-badge[:material/bug_report: " + tr("Depuración", "Debug") + "]")
    st.divider()
    table([{tr("Puerto", "Port"): row["port"], tr("Proceso", "Process"): row["process"],
            tr("Lenguaje", "Language"): row["language"],
            tr("Alcance", "Reach"): dev.SCOPE_LABELS[row["scope"]][lang == "en"],
            tr("Direcciones", "Addresses"): ", ".join(str(a) for a in row["addresses"]),
            tr("Clientes", "Clients"): len(row["clients"]), "PID": row["pid"],
            tr("Inicio", "Started"): row["started"], tr("Ruta", "Path"): row["path"]} for row in rows],
          key="dev-servers", windowed=False, lang=lang, dates=(tr("Inicio", "Started"),))


def _languages(snapshot, lang, tr):
    groups = dev_view.runtimes(snapshot)
    if not groups:
        empty(tr("No hay procesos de lenguajes de programación en marcha.", "No programming-language processes running."))
        return
    frame = pd.DataFrame([{"lenguaje": group["language"], "MB": group["memory_mb"], "color": group["color"]}
                          for group in groups])
    figure = px.bar(frame, x="MB", y="lenguaje", orientation="h", color="lenguaje",
                    color_discrete_map={row["lenguaje"]: row["color"] for row in frame.to_dict("records")},
                    labels={"lenguaje": "", "MB": tr("Memoria (MB)", "Memory (MB)")})
    figure.update_layout(showlegend=False, height=60 + 40 * len(groups), margin=dict(l=0, r=0, t=10, b=0))
    chart(figure, key="dev-languages")
    for group in groups:
        with st.expander(f"{group['language']} · {len(group['processes'])} "
                         + tr("procesos", "processes") + f" · {group['memory_mb']} MB",
                         expanded=group["key"] in {"java", "node", "python"}):
            table([{"PID": p["pid"], tr("Proceso", "Process"): p["name"],
                    tr("Aplicación", "Application"): p.get("target"), tr("Lanzado por", "Started by"): p.get("parent"),
                    tr("Puertos", "Ports"): ", ".join(str(port) for port in p["ports"]),
                    "MB": p.get("memory_mb"), tr("Inicio", "Started"): p.get("started"),
                    tr("Comando", "Command"): p.get("command")} for p in group["processes"]],
                  key=f"dev-runtime-{group['key']}", windowed=False, lang=lang, searchable=False,
                  dates=(tr("Inicio", "Started"),))


@st.cache_data(ttl=60, show_spinner=False)
def _listen_history(database: str, since: str) -> dict:
    from dataclasses import replace
    from pathlib import Path

    from infrastructure.sqlite.dev_queries import SQLiteDevQueries
    from settings import Settings
    return SQLiteDevQueries(replace(Settings(), database_path=Path(database))).listen_history(since)


def _timeline(database: str, since: str, include_all: bool, lang, tr):
    segments = dev_view.timeline(_listen_history(database, since), include_all)
    if not segments:
        empty(tr("Aún no hay recolecciones con servidores en la ventana.", "No collections with servers in the window yet."))
        return
    frame = pd.DataFrame(segments)
    frame["start"], frame["end"] = local_series(frame["start"]), local_series(frame["end"])
    frame["alcance"] = frame["scope"].map(lambda scope: dev.SCOPE_LABELS[scope][lang == "en"])
    colors = {row["language"]: row["color"] for row in segments}
    figure = px.timeline(frame, x_start="start", x_end="end", y="server", color="language",
                         color_discrete_map=colors, hover_data={"alcance": True, "language": False},
                         labels={"server": "", "language": "", "alcance": tr("Alcance", "Reach")})
    figure.update_yaxes(autorange="reversed")
    figure.update_layout(height=120 + 28 * frame["server"].nunique(), margin=dict(l=0, r=0, t=10, b=0),
                         legend=dict(orientation="h", y=1.08))
    chart(figure, key="dev-timeline")
    st.caption(tr("Cada barra es el tiempo en que las recolecciones vieron el servidor escuchando. Un hueco es una caída "
                  "o el equipo apagado; un arranque fuera de horario merece una mirada.",
                  "Each bar is the time collections saw the server listening. A gap is a stop or the computer off; "
                  "a start outside your usual hours deserves a look."))


def _port_lookup(snapshot, lang, tr):
    port = st.number_input(tr("Puerto", "Port"), min_value=1, max_value=65535, value=None, step=1,
                           placeholder="8080", key="dev-port")
    if port is None:
        st.caption(tr("Escriba un puerto para ver qué programa lo tiene abierto (p. ej. cuando «el puerto 3000 ya está "
                      "en uso»).", "Type a port to see which program holds it (e.g. when “port 3000 is already in use”)."))
        return
    processes = {row["pid"]: row for row in snapshot.get("processes", [])}
    listeners = [row for row in snapshot.get("connections", [])
                 if row.get("lport") == port and row.get("direction") == "listen"]
    connected = [row for row in snapshot.get("connections", [])
                 if row.get("lport") == port and row.get("direction") == "inbound"]
    if not listeners:
        st.success(tr(f"Nadie escucha en el puerto {port}: está libre.", f"Nothing listens on port {port}: it is free."))
        return
    for pid in dict.fromkeys(row.get("pid") for row in listeners):
        rows = [row for row in listeners if row.get("pid") == pid]
        process = processes.get(pid, {})
        name = rows[0].get("process_name") or "?"
        with st.container(border=True):
            runtime = dev.runtime(name, rows[0].get("process_path"))
            st.markdown(f"**{plain_label(name)}** · PID {pid} · {plain_label(runtime.label)}")
            st.text(tr("Escucha en: ", "Listens on: ") + ", ".join(str(row.get("laddr")) for row in rows))
            if rows[0].get("process_path"):
                st.text(rows[0]["process_path"])
            if process.get("command"):
                st.code(process["command"], language=None, wrap_lines=True)
            st.caption(tr(f"{sum(row.get('pid') == pid for row in connected)} conexiones activas a este puerto. "
                          "Atalaya no detiene procesos; si quiere liberar el puerto, copie uno de estos comandos:",
                          f"{sum(row.get('pid') == pid for row in connected)} active connections to this port. "
                          "Atalaya does not stop processes; to free the port, copy one of these commands:"))
            if pid:
                st.code(f"Stop-Process -Id {int(pid)}", language="powershell")
                st.code(f"taskkill /PID {int(pid)} /F", language="batch")


def _notice_history(notices, lang, tr):
    if not notices:
        empty(tr("Sin avisos de red en la ventana. Los genera Atalaya junto al reloj (icono de la bandeja).",
                 "No network notices in the window. Atalaya next to the clock (tray icon) creates them."))
        return
    frame = pd.DataFrame(notices)
    frame["hora"] = local_series(frame["ts"]).dt.floor("h")
    frame["tipo"] = frame["kind"].map(lambda kind: NOTICE_KINDS.get(kind, (kind, kind))[lang == "en"])
    counts = frame.groupby(["hora", "tipo"]).size().reset_index(name="total")
    chart(px.bar(counts, x="hora", y="total", color="tipo", labels={"hora": "", "total": "", "tipo": ""}),
          key="dev-notices-chart")
    table([{tr("Fecha", "Date"): n["ts"], tr("Tipo", "Kind"): NOTICE_KINDS.get(n["kind"], (n["kind"],) * 2)[lang == "en"],
            tr("Red", "Network"): n.get("network"), "IP": n.get("remote_ip"), tr("Puerto", "Port"): n.get("lport"),
            tr("Proceso", "Process"): n.get("process_name"), tr("Detalle", "Detail"): n.get("detail")} for n in notices],
          key="dev-notices", lang=lang, dates=(tr("Fecha", "Date"),))
