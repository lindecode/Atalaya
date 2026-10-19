# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Docker tab of the Desarrollo page: containers by Compose project, networks (node map), volumes and images.

Everything is read live and read-only. Names, images, paths and commands come from Docker, so they are shown as
data (tables, st.text, code blocks or escaped labels), never as Markdown or HTML.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from application import docker_view
from domain import dev
from interfaces.gui.components import empty, plain_label, table
from interfaces.gui.node_map import node_map

SCOPE_BADGES = {dev.SCOPE_LOCAL: "green", dev.SCOPE_LAN: "orange", dev.SCOPE_ALL: "red"}
STATE_BADGES = {"running": "green", "exited": "gray", "created": "gray", "paused": "orange", "restarting": "orange",
                "dead": "red", "unhealthy": "red"}


@st.cache_data(ttl=15, show_spinner=False)
def _inventory() -> dict:
    from infrastructure.docker.inventory import inventory
    return inventory()


def docker_tab(settings, lang: str, tr):
    data = _inventory()
    if not data.get("available"):
        st.info(tr("Docker no está disponible: ", "Docker is not available: ") + str(data.get("error") or ""),
                icon=":material/deployed_code:")
        st.caption(tr("Abra Docker Desktop y esta pestaña se llenará sola. Mientras tanto, las alertas de Docker usan lo "
                      "último que se recolectó.", "Open Docker Desktop and this tab fills in by itself. Meanwhile, "
                      "Docker alerts use the last collected data."))
        return
    version = data.get("version") or {}
    st.caption(f"Docker {version.get('server')} · {version.get('os')} · " + tr("contexto ", "context ")
               + str(version.get("context") or "default"))
    for warning in data.get("warnings", []):
        st.caption(":orange[" + plain_label(warning) + "]")
    totals = docker_view.summary(data)
    cols = st.columns(6)
    cols[0].metric(tr("En marcha", "Running"), f"{totals['running']}/{totals['total']}")
    cols[1].metric(tr("Puertos a la red", "Ports on the network"), totals["exposed"],
                   help=tr("Publicados en todas las interfaces o en la red local.", "Published on every interface or the LAN."))
    cols[2].metric(tr("Con riesgos", "At risk"), totals["at_risk"])
    cols[3].metric(tr("Con problemas", "With problems"), totals["unhealthy"],
                   help=tr("unhealthy o terminados por falta de memoria (OOM).", "Unhealthy or killed for lack of memory (OOM)."))
    cols[4].metric(tr("Imágenes huérfanas", "Dangling images"), totals["dangling_images"])
    cols[5].metric(tr("Volúmenes sin uso", "Unused volumes"), totals["unused_volumes"])
    sections = {"containers": tr("Contenedores", "Containers"), "networks": tr("Redes", "Networks"),
                "volumes": tr("Volúmenes", "Volumes"), "images": tr("Imágenes", "Images")}
    section = st.segmented_control(tr("Sección", "Section"), list(sections), format_func=sections.get,
                                   default="containers", key="docker-section", label_visibility="collapsed")
    if section == "networks":
        _networks(data, lang, tr)
    elif section == "volumes":
        _volumes(data, lang, tr)
    elif section == "images":
        _images(settings, data, lang, tr)
    else:
        _containers(data, lang, tr)


def _containers(data, lang, tr):
    if not data.get("containers"):
        empty(tr("No hay contenedores.", "No containers."))
        return
    for project, containers in docker_view.by_project(data["containers"]):
        st.markdown("#### " + (plain_label(project) if project else tr("Sin proyecto de Compose", "No Compose project")))
        for start in range(0, len(containers), 2):
            for column, container in zip(st.columns(2), containers[start:start + 2]):
                with column.container(border=True):
                    _container_card(container, lang, tr)


def _container_card(container, lang, tr):
    state = docker_view.state_of(container)
    st.markdown(f"**{plain_label(container['name'])}** :{STATE_BADGES.get(state, 'gray')}-badge[{plain_label(state)}]"
                + (" :red-badge[OOM]" if container.get("oom_killed") else ""))
    st.text(str(container.get("image") or ""))
    ports = container.get("published", [])
    if ports:
        st.markdown(" ".join(f":{SCOPE_BADGES[p['scope']]}-badge[{p['host_ip']}:{p['host_port']} → {p['container_port']}]"
                             for p in ports))
    usage = " · ".join(part for part in (
        f"CPU {container['cpu']}" if container.get("cpu") else "", str(container.get("memory") or ""),
        tr(f"{container['restart_count']} reinicios", f"{container['restart_count']} restarts")
        if container.get("restart_count") else "") if part)
    if usage:
        st.caption(usage)
    risks = container.get("risks", [])
    if risks:
        # One box per container; Docker's text goes inside inline code (literal, so "--privileged" stays as typed)
        literal = lambda text: "`" + str(text).replace("`", "") + "`"
        lines = [f"- {literal(risk['detail'])}: " + (literal(risk["fix"]) if risk["fix"].startswith("-p ") else risk["fix"])
                 for risk in risks]
        box = st.error if docker_view.worst_risk(container) in {"high", "critical"} else st.warning
        box("\n".join(lines), icon=":material/shield:")
    with st.expander(tr("Detalle", "Detail")):
        st.text(tr("Usuario: ", "User: ") + str(container.get("user")) + " · "
                + tr("reinicio: ", "restart: ") + str(container.get("restart_policy") or "no"))
        if container.get("networks"):
            st.text(tr("Redes: ", "Networks: ") + ", ".join(f"{n['name']} ({n['ip'] or '—'})" for n in container["networks"]))
        if container.get("mounts"):
            st.dataframe(pd.DataFrame([{tr("Tipo", "Type"): m["type"], tr("Origen", "Source"): m["name"] or m["source"],
                                        tr("Destino", "Destination"): m["destination"], "RW": m["rw"]}
                                       for m in container["mounts"]]), hide_index=True, width="stretch")
        if container.get("state") != "running" and container.get("exit_code") is not None:
            st.text(tr("Código de salida: ", "Exit code: ") + str(container["exit_code"]))


def _networks(data, lang, tr):
    rows = docker_view.network_rows(data)
    graph = docker_view.network_graph(data, lang)
    if len(graph["nodes"]) > 1:
        left, right = st.columns([2, 1])
        with left:
            selected = node_map(graph, key="docker-map", label=tr("Redes y contenedores", "Networks and containers"))
        with right:
            chosen = next((row for row in rows if f"n:{row['name']}" == selected), None)
            if chosen:
                st.markdown(f"**{plain_label(chosen['name'])}**")
                st.text(f"{chosen['driver']} · {chosen.get('subnet') or '—'} · gateway {chosen.get('gateway') or '—'}"
                        + (tr(" · interna", " · internal") if chosen["internal"] else ""))
                st.dataframe(pd.DataFrame(chosen["containers"]), hide_index=True, width="stretch")
            elif selected and selected.startswith("c:"):
                container = next((c for c in data["containers"] if c["name"] == selected[2:]), None)
                if container:
                    with st.container(border=True):
                        _container_card(container, lang, tr)
            else:
                st.info(tr("Haga clic en una red o un contenedor.", "Click a network or a container."),
                        icon=":material/touch_app:")
        st.caption(tr("Relleno del contenedor: verde en marcha, gris detenido, rojo con problemas; borde rojo/ámbar: "
                      "tiene riesgos. Las redes sin contenedores solo aparecen en la tabla.",
                      "Container fill: green running, grey stopped, red with problems; red/amber border: it has risks. "
                      "Networks without containers only appear in the table."))
    table([{tr("Red", "Network"): row["name"], "Driver": row["driver"], tr("Subred", "Subnet"): row["subnet"],
            "Gateway": row["gateway"], tr("Interna", "Internal"): row["internal"],
            tr("Contenedores", "Containers"): ", ".join(m["name"] for m in row["containers"])} for row in rows],
          key="docker-networks", windowed=False, lang=lang, searchable=False)


def _volumes(data, lang, tr):
    rows = docker_view.volume_rows(data)
    table([{tr("Volumen", "Volume"): row["name"][:12] + "…" if row["anonymous"] else row["name"],
            tr("Proyecto", "Project"): row["project"], tr("Usado por", "Used by"): ", ".join(row["used_by"]) or "—",
            tr("Anónimo", "Anonymous"): row["anonymous"], tr("Creado", "Created"): row["created"]} for row in rows],
          key="docker-volumes", windowed=False, lang=lang, dates=(tr("Creado", "Created"),))
    unused = [row for row in rows if not row["used_by"]]
    if unused:
        st.caption(tr(f"{len(unused)} volúmenes no los usa ningún contenedor. Pueden contener datos: revíselos antes de "
                      "borrar. Para quitar los sin uso:", f"{len(unused)} volumes are used by no container. They may hold "
                      "data: check before deleting. To remove unused ones:"))
        st.code("docker volume prune", language=None)
    mounts = docker_view.bind_mounts(data)
    if mounts:
        st.markdown("**" + tr("Carpetas del equipo montadas en contenedores", "Host folders mounted into containers") + "**")
        table([{tr("Contenedor", "Container"): m["container"], tr("Carpeta del equipo", "Host folder"): m["source"],
                tr("Dentro del contenedor", "Inside the container"): m["destination"], tr("Escritura", "Writable"): m["rw"],
                tr("Sensible", "Sensitive"): m["sensitive"]} for m in mounts],
              key="docker-binds", windowed=False, lang=lang, searchable=False)


def _images(settings, data, lang, tr):
    rows = docker_view.image_rows(data)
    table([{tr("Imagen", "Image"): row["image"], "ID": row["id"], tr("Tamaño", "Size"): row["size"],
            tr("Creada", "Created"): row["created"], tr("Días", "Days"): row["age_days"],
            tr("Contenedores", "Containers"): ", ".join(row["containers"]) or "—",
            tr("Huérfana", "Dangling"): row["dangling"], "latest": row["latest"]} for row in rows],
          key="docker-images", windowed=False, lang=lang, dates=(tr("Creada", "Created"),))
    dangling = [row for row in rows if row["dangling"]]
    if dangling:
        st.caption(tr(f"{len(dangling)} imágenes huérfanas (capas sin etiqueta de compilaciones anteriores). Para "
                      "recuperar el espacio:", f"{len(dangling)} dangling images (untagged layers from earlier builds). "
                      "To reclaim the space:"))
        st.code("docker image prune", language=None)
    latest = [row["image"] for row in rows if row["latest"] and row["containers"]]
    if latest:
        st.caption(tr("Contenedores sobre «latest»: no sabrá qué versión corre ni cuándo cambió. Fije una versión "
                      "(p. ej. postgres:16.4).", "Containers on “latest”: you cannot tell which version runs or when it "
                      "changed. Pin a version (e.g. postgres:16.4)."))
    _scout(settings, [row["image"] for row in rows if not row["dangling"]], tr)


def _scout(settings, images, tr):
    from bootstrap import build_automation_config_service
    with st.container(border=True):
        st.markdown("**Docker Scout** · " + tr("vulnerabilidades conocidas", "known vulnerabilities"))
        if not build_automation_config_service(settings).load().docker_scout:
            st.caption(tr("Desactivado. Scout envía la lista de paquetes de la imagen al servicio de Docker; actívelo en "
                          "Ajustes → Funciones si está de acuerdo.", "Off. Scout sends the image's package list to "
                          "Docker's service; turn it on in Settings → Features if you agree."))
            return
        if not images:
            return
        image = st.selectbox(tr("Imagen", "Image"), images, key="docker-scout-image")
        if st.button(tr("Analizar con Docker Scout", "Analyse with Docker Scout"), icon=":material/policy:",
                     key="docker-scout-run"):
            from infrastructure.docker.cli import DockerCLI, DockerUnavailable
            cli = DockerCLI()
            if not cli.scout_available():
                st.warning(tr("Docker Scout no está instalado en el CLI de Docker.", "Docker Scout is not installed."))
                return
            with st.spinner(tr("Consultando Docker Scout…", "Querying Docker Scout…")):
                try:
                    st.code(cli.scout_quickview(image), language=None)
                except (DockerUnavailable, ValueError) as exc:
                    st.error(str(exc))
