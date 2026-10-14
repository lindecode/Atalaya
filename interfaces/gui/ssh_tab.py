"""SSH tab of the Desarrollo page: servers this computer connects to, its tunnels, and who reaches its own SSH."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from application import ssh_view
from domain import dev
from interfaces.gui.components import empty, legend, plain_label, table
from interfaces.gui.node_map import node_map
from interfaces.gui.table_formatting import to_local_datetime


@st.cache_data(ttl=60, show_spinner=False)
def _history(database: str, since: str) -> list[dict]:
    from dataclasses import replace
    from pathlib import Path

    from infrastructure.sqlite.dev_queries import SQLiteDevQueries
    from settings import Settings
    return SQLiteDevQueries(replace(Settings(), database_path=Path(database))).ssh_history(since)


@st.cache_data(ttl=300, show_spinner=False)
def _names(database: str, ips: tuple[str, ...]) -> dict[str, str]:
    from dataclasses import replace
    from pathlib import Path

    from infrastructure.sqlite.queries import SQLiteQueryRepository
    from interfaces.gui.network import name_map
    from settings import Settings
    try:
        return name_map(SQLiteQueryRepository(replace(Settings(), database_path=Path(database))).ip_names(ips))
    except Exception:
        return {}


def ssh_tab(settings, snapshot: dict, since: str, lang: str, tr):
    database = str(settings.database_path)
    history = _history(database, since)
    ips = tuple(sorted({row["remote_address"] for row in history if row.get("remote_address")}))
    data = ssh_view.model(history, snapshot, _names(database, ips))
    sessions, inbound = data["sessions"], data["inbound"]
    a, b, c, d = st.columns(4)
    a.metric(tr("Sesiones ahora", "Sessions now"), sum(s["live"] for s in sessions))
    b.metric(tr("Servidores en la ventana", "Servers in the window"), len(sessions))
    c.metric(tr("Túneles", "Tunnels"), sum(bool(s["tunnels"]) for s in sessions),
             help=tr("Sesiones con -L, -R o -D.", "Sessions with -L, -R or -D."))
    d.metric(tr("Entradas a su SSH", "Into your SSH"), len(inbound),
             help=tr("Equipos de la red o de Internet que se conectaron al servidor SSH de este equipo.",
                     "Hosts on the network or the Internet that connected to this computer's SSH server."))
    for session in sessions:
        for risk in session["risks"]:
            (st.error if risk["severity"] == "high" else st.warning)(
                f"{plain_label(session['name'] or session['remote'])}:{session['port']}: {risk['text'][lang == 'en']}",
                icon=":material/vpn_key:")
    if not sessions and not inbound:
        empty(tr("No hay sesiones SSH con otros equipos en la ventana.", "No SSH sessions with other hosts in the window."))
        return
    legend([(tr("Conectado ahora", "Connected now"), "#22c55e"), (tr("Servidor en red local", "LAN server"), "#3b82f6"),
            (tr("Servidor en Internet", "Internet server"), "#ef4444"), (tr("Puerto de túnel", "Tunnel port"), "#a855f7")])
    left, right = st.columns([2, 1])
    with left:
        selected = node_map(ssh_view.graph(data, lang), key="ssh-map", label=tr("Mapa de conexiones SSH", "SSH connection map"))
    with right:
        _detail(selected, sessions, inbound, lang, tr)
    st.caption(tr("Línea continua verde: sesión abierta ahora; discontinua: sesión vista en la ventana que ya terminó. "
                  "Atalaya solo guarda las opciones de ssh (-L, -R, -D, -A), nunca destinos ni comandos.",
                  "Solid green line: session open now; dashed: a session seen in the window that has ended. "
                  "Atalaya keeps only ssh options (-L, -R, -D, -A), never destinations or commands."))
    table([{tr("Servidor", "Server"): s["remote"], tr("Nombre", "Name"): s["name"], tr("Puerto", "Port"): s["port"],
            tr("Ahora", "Now"): s["live"], tr("Túneles", "Tunnels"): ", ".join(
                ssh_view.TUNNEL_LABELS.get(t, (t, t))[lang == "en"] for t in s["tunnels"]),
            tr("Reenvío de agente", "Agent forwarding"): s["agent_forwarding"],
            tr("Primera vez", "First seen"): s["first_seen"], tr("Última vez", "Last seen"): s["last_seen"]}
           for s in sessions], key="ssh-sessions", windowed=True, lang=lang, searchable=False,
          dates=(tr("Primera vez", "First seen"), tr("Última vez", "Last seen")))
    if inbound:
        st.markdown("**" + tr("Conexiones entrantes a su servidor SSH", "Connections into your SSH server") + "**")
        table([{tr("Origen", "Source"): i["remote"], tr("Nombre", "Name"): i["name"], tr("Red", "Network"): i["origin"],
                tr("Puerto", "Port"): i["port"], tr("Última vez", "Last seen"): i["last_seen"]} for i in inbound],
              key="ssh-inbound", windowed=True, lang=lang, searchable=False, dates=(tr("Última vez", "Last seen"),))


def _detail(selected, sessions, inbound, lang, tr):
    session = next((s for s in sessions if f"s:{s['remote']}:{s['port']}" == selected), None)
    if session:
        with st.container(border=True):
            st.markdown(f"**`{str(session['remote']).replace('`', '')}:{session['port']}`**")
            if session["name"]:
                st.text(session["name"])
            st.caption({"lan": tr("Red local", "Local network"), "internet": "Internet"}.get(session["origin"], "?")
                       + " · " + (tr("conectado ahora", "connected now") if session["live"] else
                                  tr("última vez ", "last seen ") + _when(session["last_seen"])))
            for tunnel in session["tunnels"]:
                st.text(ssh_view.TUNNEL_LABELS.get(tunnel, (tunnel, tunnel))[lang == "en"])
            for listener in session["listeners"]:
                st.text(tr(f"Puerto local :{listener['port']} en {listener['address']} · {listener['users']} apps conectadas",
                           f"Local port :{listener['port']} on {listener['address']} · {listener['users']} apps connected"))
            for risk in session["risks"]:
                st.warning(risk["text"][lang == "en"], icon=":material/warning:")
        return
    if selected and selected.startswith("t:"):
        port = selected[2:]
        st.info(tr(f"Puerto :{port} que abrió ssh en este equipo: las aplicaciones que lo usan salen por el túnel.",
                   f"Port :{port} opened by ssh on this computer: apps using it go out through the tunnel."),
                icon=":material/route:")
        return
    st.info(tr("Haga clic en un servidor del mapa.", "Click a server on the map."), icon=":material/touch_app:")


def _when(value) -> str:
    local = to_local_datetime(value)
    return local.strftime("%d/%m %H:%M") if hasattr(local, "strftime") else "—"
