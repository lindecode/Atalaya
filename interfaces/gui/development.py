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
                "exposed": ("Servidor expuesto", "Exposed server")}


@st.cache_data(ttl=5, show_spinner=False)
def _snapshot() -> dict:
    from infrastructure.windows.dev_inventory import snapshot
    return snapshot()


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

    from infrastructure.windows.live_network import firewall_readable
    if not firewall_readable(settings.firewall_log_path):
        st.warning(tr("No se puede leer el log del firewall: los pings y escaneos no se detectan. Vaya a Ajustes → "
                      "Permisos ampliados → Configurar permisos.", "The firewall log cannot be read: pings and scans "
                      "are not detected. Go to Settings → Extended permissions → Configure permissions."),
                   icon=":material/lock:")

    @st.fragment(run_every="10s" if live else None)
    def body():
        try:
            snapshot = _snapshot()
        except Exception as exc:
            st.error(tr(f"No se pudo leer el estado de la red: {exc}", f"Could not read the network state: {exc}"))
            return
        rows = dev_view.servers(snapshot, include_all=include_all)
        notices = _notices(settings, since)
        _kpis(rows, notices, tr)
        exposed_debug = [row for row in rows if row["debug"] and row["scope"] != dev.SCOPE_LOCAL]
        for row in exposed_debug:
            st.error(tr(f"Puerto de depuración expuesto: {row['debug']} en :{row['port']} ({plain_label(row['process'])}). "
                        "Quien lo alcance puede ejecutar código; hágalo escuchar solo en 127.0.0.1.",
                        f"Exposed debug port: {row['debug']} on :{row['port']} ({plain_label(row['process'])}). "
                        "Whoever reaches it can run code; bind it to 127.0.0.1."), icon=":material/bug_report:")
        map_tab, servers_tab, languages_tab, notices_tab = st.tabs([
            ":material/hub: " + tr("Mapa", "Map"), ":material/dns: " + tr("Servidores", "Servers"),
            ":material/code: " + tr("Lenguajes", "Languages"),
            ":material/notifications: " + tr("Avisos de red", "Network notices")])
        with map_tab:
            _map(rows, notices, local_clients, lang, tr)
        with servers_tab:
            _servers(rows, lang, tr)
        with languages_tab:
            _languages(snapshot, lang, tr)
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
