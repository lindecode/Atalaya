# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
    active_forwards = [(s, f) for s in sessions for f in s.get("forwards", []) if f["active"]]
    c.metric(tr("Túneles activos", "Active tunnels"), len(active_forwards),
             help=tr("Puertos reenviados ahora por ssh -L/-R/-D, ~/.ssh/config o VS Code Remote-SSH.",
                     "Ports forwarded now by ssh -L/-R/-D, ~/.ssh/config or VS Code Remote-SSH."))
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
    if active_forwards:
        st.markdown("**" + tr("Túneles activos", "Active tunnels") + "**")
        table([{tr("Puerto local", "Local port"): f":{f['listen']}" if f["kind"] != "remote" else "—",
                tr("Lleva a", "Leads to"): _leads_to(s, f, lang),
                tr("Tipo", "Kind"): ssh_view.FORWARD_KINDS[f["kind"]][lang == "en"], tr("Vía", "Via"): f["via"],
                tr("Escucha en", "Listens on"): dev.SCOPE_LABELS[f["scope"]][lang == "en"] if f["kind"] != "remote" else "—",
                tr("Conexiones ahora", "Connections now"): f["users"]} for s, f in active_forwards],
              key="ssh-forwards", windowed=False, lang=lang, searchable=False)
    table([{tr("Servidor", "Server"): s["remote"], tr("Nombre", "Name"): s.get("alias") or s["name"],
            tr("Puerto", "Port"): s["port"],
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


def _leads_to(session, item, lang) -> str:
    server = session.get("alias") or session.get("name") or session["remote"]
    if item["kind"] == "dynamic":
        return ("anywhere, through " if lang == "en" else "cualquier destino, a través de ") + server
    if item["kind"] == "remote":
        return (f"{server} :{item['listen']} → this computer {item['target']}" if lang == "en"
                else f"{server} :{item['listen']} → este equipo {item['target']}")
    return f"{server} → {item['target']}"


def _detail(selected, sessions, inbound, lang, tr):
    session = next((s for s in sessions if f"s:{s['remote']}:{s['port']}" == selected), None)
    if session:
        with st.container(border=True):
            st.markdown(f"**`{str(session['remote']).replace('`', '')}:{session['port']}`**")
            name = session.get("alias") or session.get("name")
            if name:
                st.text(name)
            st.caption({"lan": tr("Red local", "Local network"), "internet": "Internet"}.get(session.get("origin"), "?")
                       + " · " + (tr("conectado ahora", "connected now") if session.get("live") else
                                  tr("última vez ", "last seen ") + _when(session.get("last_seen"))))
            for tunnel in session.get("tunnels", []):
                st.text(ssh_view.TUNNEL_LABELS.get(tunnel, (tunnel, tunnel))[lang == "en"])
            for f in session.get("forwards", []):
                if f.get("kind") == "remote":
                    st.text(tr(f"Túnel inverso :{f['listen']} en el servidor",
                               f"Reverse tunnel :{f['listen']} on server"))
                elif f.get("active"):
                    scope = dev.SCOPE_LABELS.get(f.get("scope"), ("local", "local"))[lang == "en"]
                    users = f" · {f['users']} " + tr("apps conectadas", "apps connected") if f.get("users") is not None else ""
                    st.text(tr(f"Puerto local :{f['listen']} ({scope}){users}",
                               f"Local port :{f['listen']} ({scope}){users}"))
            for listener in session.get("listeners", []):
                st.text(tr(f"Puerto local :{listener['port']} en {listener.get('address', '127.0.0.1')} · {listener.get('users', 0)} apps conectadas",
                           f"Local port :{listener['port']} on {listener.get('address', '127.0.0.1')} · {listener.get('users', 0)} apps connected"))
            for risk in session.get("risks", []):
                st.warning(risk["text"][lang == "en"], icon=":material/warning:")
        return
    tunnel = next(((s, f) for s in sessions for f in s.get("forwards", [])
                   if ssh_view.tunnel_node_id(s, f) == selected), None)
    if tunnel:
        session, item = tunnel
        with st.container(border=True):
            st.markdown("**:material/route: " + ssh_view.FORWARD_KINDS[item["kind"]][lang == "en"] + "**")
            if item["kind"] == "remote":
                st.text(_leads_to(session, item, lang))
                st.warning(tr("Quien llegue a ese puerto del servidor entra hasta este equipo.",
                              "Whoever reaches that server port gets into this computer."), icon=":material/warning:")
            else:
                st.text(tr(f"localhost:{item['listen']} en este equipo", f"localhost:{item['listen']} on this computer"))
                st.text("↓ SSH " + str(session.get("alias") or session["remote"]))
                st.text(item["target"] or tr("cualquier destino (proxy SOCKS)", "any destination (SOCKS proxy)"))
                st.caption(tr(f"Abierto por {item['owner'] or '?'} · {item['users']} conexiones ahora · "
                              f"escucha en {dev.SCOPE_LABELS[item['scope']][0].lower()}",
                              f"Opened by {item['owner'] or '?'} · {item['users']} connections now · "
                              f"listens on {dev.SCOPE_LABELS[item['scope']][1].lower()}"))
            st.caption(tr("Origen: ", "Source: ") + item["via"])
        return
    inbound_item = next((i for i in inbound if f"i:{i['remote']}:{i['port']}" == selected), None)
    if inbound_item:
        with st.container(border=True):
            st.markdown(f"**`{str(inbound_item['remote']).replace('`', '')}:{inbound_item['port']}`**")
            if inbound_item.get("name"):
                st.text(inbound_item["name"])
            st.caption({"lan": tr("Red local", "Local network"), "internet": "Internet"}.get(inbound_item.get("origin"), "?")
                       + " · " + tr("Conexión entrante a su servidor SSH", "Inbound connection to your SSH server"))
            st.caption(tr("Última vez visto: ", "Last seen: ") + _when(inbound_item.get("last_seen")))
        return
    if selected == "host":
        with st.container(border=True):
            st.markdown("**" + tr("Este equipo (PC)", "This computer (PC)") + "**")
            st.caption(tr("Punto central de conexiones y túneles SSH.", "Central point for SSH connections and tunnels."))
        return
    st.info(tr("Haga clic en un servidor del mapa.", "Click a server on the map."), icon=":material/touch_app:")


def _when(value) -> str:
    local = to_local_datetime(value)
    return local.strftime("%d/%m %H:%M") if hasattr(local, "strftime") else "—"
