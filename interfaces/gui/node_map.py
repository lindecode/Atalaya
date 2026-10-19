# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Clickable node map (SVG) built with st.components.v2.

Components v2 are not sandboxed: the JavaScript runs in the page. Labels come from collected data (process names,
IPs), so the script only ever sets them through textContent and SVG attributes, never innerHTML, and colours are
checked against a hex pattern before use.
"""
from __future__ import annotations

import streamlit as st

CSS = """
:host { display: block; }
.map { width: 100%; color: var(--st-text-color, currentColor); font-family: var(--st-font, sans-serif); }
svg { width: 100%; height: auto; max-height: 720px; display: block; margin: 0 auto; }
.node { cursor: pointer; }
.node text { fill: currentColor; font-size: 13px; font-weight: 600; pointer-events: none; }
.node.host text { fill: #ffffff; font-size: 12px; }
.node text.sub { opacity: .7; font-size: 10.5px; font-weight: 400; }
.node circle { transition: stroke-width .15s; }
.node:hover circle, .node.selected circle { stroke-width: 4; }
.dim { opacity: .18; }
.edge { transition: opacity .15s; }
"""

JS = r"""
const NS = "http://www.w3.org/2000/svg";
const HEX = /^#[0-9a-fA-F]{6}$/;
const color = (value, fallback) => HEX.test(value || "") ? value : fallback;

function el(name, attrs) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, String(value));
  return node;
}

export default function(component) {
  const { data, parentElement, setStateValue } = component;
  let root = parentElement.querySelector(".map");
  if (!root) { root = document.createElement("div"); root.className = "map"; parentElement.appendChild(root); }
  root.replaceChildren();
  if (!data || !Array.isArray(data.nodes)) return;
  // Fit the drawing to the nodes (labels included) instead of a square around the centre
  const xs = data.nodes.flatMap((n) => [Number(n.x) - (Number(n.r) || 10) - 75, Number(n.x) + (Number(n.r) || 10) + 75]);
  const ys = data.nodes.flatMap((n) => [Number(n.y) - (Number(n.r) || 10) - 20, Number(n.y) + (Number(n.r) || 10) + 34]);
  const [left, right, top, bottom] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const width = Math.max(right - left, 560), height = Math.max(bottom - top, 380);  // sparse maps: no giant labels
  const svg = el("svg", { viewBox: `${left - (width - (right - left)) / 2} ${top - (height - (bottom - top)) / 2} ${width} ${height}`,
                          role: "img", "aria-label": String(data.label || "") });
  const edgesLayer = el("g"), nodesLayer = el("g");
  svg.append(edgesLayer, nodesLayer);
  const byId = new Map(data.nodes.map((node) => [String(node.id), node]));
  const edgeEls = [];
  for (const edge of data.edges || []) {
    const a = byId.get(String(edge.from)), b = byId.get(String(edge.to));
    if (!a || !b) continue;
    const line = el("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "edge",
                              stroke: color(edge.color, "#94a3b8"), "stroke-width": Number(edge.width) || 1,
                              "stroke-opacity": edge.dashed ? 0.55 : 0.85 });
    if (edge.dashed) line.setAttribute("stroke-dasharray", "5 5");
    edgesLayer.appendChild(line);
    edgeEls.push({ line, from: String(edge.from), to: String(edge.to) });
  }
  const nodeEls = new Map();
  for (const node of data.nodes) {
    const id = String(node.id);
    const group = el("g", { class: node.kind === "host" ? "node host" : "node", transform: `translate(${Number(node.x) || 0} ${Number(node.y) || 0})`,
                            tabindex: 0 });
    const radius = Number(node.r) || 10;
    group.appendChild(el("circle", { r: radius, fill: color(node.color, "#94a3b8"),
                                     stroke: color(node.ring, "#ffffff"), "stroke-width": node.ring ? 4 : 1.5 }));
    const title = el("title"); title.textContent = [node.label, node.sub, node.tip].filter(Boolean).join(" · ");
    group.appendChild(title);
    const below = node.kind !== "host";
    const label = el("text", { "text-anchor": "middle", y: below ? radius + 13 : 4 });
    label.textContent = String(node.label || "");
    group.appendChild(label);
    if (node.sub) {
      const sub = el("text", { class: "sub", "text-anchor": "middle", y: radius + 25 });
      sub.textContent = String(node.sub);
      group.appendChild(sub);
    }
    const choose = () => { select(id); setStateValue("selected", id); };
    group.addEventListener("click", choose);
    group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") choose(); });
    nodesLayer.appendChild(group);
    nodeEls.set(id, group);
  }
  function select(id) {
    const linked = new Set([id]);
    for (const edge of edgeEls) if (edge.from === id || edge.to === id) { linked.add(edge.from); linked.add(edge.to); }
    for (const [nodeId, group] of nodeEls) {
      group.classList.toggle("selected", nodeId === id);
      group.classList.toggle("dim", Boolean(id) && id !== "host" && !linked.has(nodeId));
    }
    for (const edge of edgeEls) {
      edge.line.classList.toggle("dim", Boolean(id) && id !== "host" && edge.from !== id && edge.to !== id);
    }
  }
  if (data.selected) select(String(data.selected));
  root.appendChild(svg);
}
"""

_component = st.components.v2.component("atalaya_node_map", css=CSS, js=JS)


def node_map(graph: dict, *, key: str, selected: str | None = None, label: str = "") -> str | None:
    """Draws the graph and returns the id of the node the person clicked (kept across reruns)."""
    result = _component(data={**graph, "selected": selected, "label": label}, key=key,
                        on_selected_change=lambda: None)
    return getattr(result, "selected", None)
