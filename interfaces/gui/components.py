from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from interfaces.gui.table_formatting import (COLUMN_FORMAT, DISPLAY_FORMAT, filter_table_rows, format_table_rows,
                                             is_date_column, to_local_datetime)
from interfaces.gui.table_views import VIEWS, column_config, present, visible


SEVERITY_ICONS = {"low": "⚪", "medium": "🟡", "high": "🟠", "critical": "🔴"}
SEVERITY_COLORS = {"low": "#94A3B8", "medium": "#EAB308", "high": "#F97316", "critical": "#EF4444"}
SEVERITY_NAMES = {"low": "Bajo", "medium": "Medio", "high": "Alto", "critical": "Crítico"}

# Static stylesheet only: nothing collected from the machine is ever interpolated into HTML here
_STYLE = """
<style>
:root {--nl-brand: #6BC043; --nl-brand-soft: rgba(107, 192, 67, .14); --nl-line: rgba(127, 127, 127, .2);}
.block-container {padding-top: 1.6rem; padding-bottom: 3rem;}
[data-testid="stMetric"] {
  background: rgba(127, 127, 127, 0.06); border: 1px solid var(--nl-line);
  border-left: 3px solid var(--nl-brand); border-radius: 12px; padding: 14px 16px 10px 16px;
}
[data-testid="stMetricLabel"] p {font-size: 0.76rem; opacity: 0.75; text-transform: uppercase; letter-spacing: .03em;}
[data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
[data-testid="stExpander"] details {border-radius: 12px;}
[data-testid="stPlotlyChart"] {max-width: 100%; overflow: hidden;}
.nl-hero {
  position: relative; overflow: hidden; border-radius: 16px; padding: 18px 22px 18px 26px; margin-bottom: 14px;
  background: linear-gradient(115deg, var(--nl-brand-soft), rgba(107, 192, 67, .03) 60%, transparent);
  border: 1px solid var(--nl-line);
}
.nl-hero::before {content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--nl-brand);}
.nl-hero h1 {font-size: 1.65rem; margin: 0 0 2px 0; padding: 0; letter-spacing: -.01em;}
.nl-hero p {margin: 0; opacity: .78;}
.nl-risk {display: flex; align-items: center; gap: 14px; border-radius: 14px; padding: 12px 18px;
  border: 1px solid rgba(127,127,127,.2); margin-bottom: 12px;}
.nl-risk .dot {width: 14px; height: 14px; border-radius: 50%; flex: none;}
.nl-risk b {font-size: 1.05rem;}
.nl-legend {display: flex; flex-wrap: wrap; gap: 16px; font-size: .85rem; opacity: .85; margin: 2px 0 6px 0;}
.nl-legend span::before {content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 3px;
  margin-right: 6px; vertical-align: middle; background: var(--c);}
[data-testid="stSidebarLogo"] {height: 3rem; max-width: 100%;}
.nl-tile {border: 1px solid var(--nl-line); border-top: 3px solid var(--c); border-radius: 10px; padding: 8px 10px;
  display: flex; flex-direction: column; gap: 1px; min-height: 96px;}
.nl-tile span {font-size: .72rem; opacity: .7; text-transform: uppercase; letter-spacing: .03em;}
.nl-tile b {color: var(--c); font-size: .95rem;}
.nl-tile small {opacity: .75;}
.nl-pill {display: inline-block; padding: 1px 10px; border-radius: 999px; font-size: .78rem; font-weight: 700;
  color: var(--c); background: color-mix(in srgb, var(--c) 16%, transparent); border: 1px solid var(--c); margin-right: 4px;}
.nl-about {text-align: center;}
.nl-about h3 {margin: 4px 0 0 0; padding: 0;}
.nl-about small {opacity: .6;}
.nl-about hr {width: 40px; margin: 14px auto;}
.nl-about p {margin: 0 0 2px 0; opacity: .75;}
.nl-about b {font-size: 1.1rem; letter-spacing: .06em; color: var(--nl-brand);}
</style>
"""

# The brand green is too light for white text: on dark, primary buttons use graphite ink (7.9:1);
# on light the primary is the darker #367C1D and keeps Streamlit's white text (5.2:1)
_DARK_STYLE = """
<style>
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primary"] p {color: #13171F;}
</style>
"""


def apply_style():
    st.markdown(_STYLE, unsafe_allow_html=True)
    if getattr(st.context.theme, "type", None) == "dark":
        st.markdown(_DARK_STYLE, unsafe_allow_html=True)


def hero(title: str, subtitle: str):
    """Page header. Only literals written in this codebase may be passed here (it renders HTML)."""
    st.markdown(f'<div class="nl-hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def risk_banner(level: str, detail: str):
    """`level` is validated against the known severities; `detail` must be a literal or a number."""
    level = level if level in SEVERITY_COLORS else "low"
    color = SEVERITY_COLORS[level]
    st.markdown(
        f'<div class="nl-risk" style="background:{color}1f"><div class="dot" style="background:{color}"></div>'
        f'<div><b>Riesgo {SEVERITY_NAMES[level].lower()}</b><br><span>{detail}</span></div></div>',
        unsafe_allow_html=True,
    )


def legend(items: list[tuple[str, str]]):
    """Colour legend; labels are literals from the codebase."""
    spans = "".join(f'<span style="--c:{color}">{label}</span>' for label, color in items)
    st.markdown(f'<div class="nl-legend">{spans}</div>', unsafe_allow_html=True)


def empty(message: str):
    st.info(message)


MARKDOWN_SPECIAL = set("\\`*_{}[]()#+-.!|~<>")
SEARCH_PAGE = "views/10_Buscar.py"
# Row fields worth pivoting on (raw names and the Spanish labels of table_views)
ENTITY_FIELDS = {"raddr", "laddr", "src_ip", "dst_ip", "source_ip", "source_host", "remote_address", "process_name",
                 "process_path", "path", "dest_path", "sha256", "target_user", "process_user", "name", "remote",
                 "remoto", "proceso", "ruta", "IP de origen", "IP de destino", "Cuenta", "Proceso", "Ruta", "SHA-256",
                 "Remoto", "Usuario"}


def plain_label(text: object) -> str:
    """Labels render Markdown (links, even images that would load a URL): escape collected text before using it."""
    return "".join("\\" + char if char in MARKDOWN_SPECIAL else char for char in str(text))


def page_link(page: str, label: str, icon: str, query_params: dict | None = None):
    """Link to another page; when a page runs on its own (tests, direct run) there is no navigation to link to."""
    try:
        st.page_link(page, label=label, icon=icon, query_params=query_params)
    except Exception:
        st.caption(f"→ {label}")


def search_links(values, key: str, limit: int = 4):
    """'Buscar «…»' links to the entity search for the distinct, meaningful values given."""
    seen = []
    for value in values:
        text = "" if value is None else str(value).strip()
        if 2 <= len(text) <= 200 and text not in seen and text not in {"-", "?", "None"}:
            seen.append(text)
    if not seen:
        return
    columns = st.columns(min(len(seen[:limit]), limit))
    for column, text in zip(columns, seen[:limit]):
        with column:
            page_link(SEARCH_PAGE, f"Buscar «{plain_label(text[:40])}»", ":material/search:", query_params={"q": text})


def csv_name(key: str, windowed: bool = True) -> str:
    """conexiones_24-horas_20261007-1055.csv: says which window and when it was exported."""
    window = str(st.session_state.get("window") or "").replace(" ", "-") if windowed else ""
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return "_".join(part for part in (key, window, stamp) if part) + ".csv"


def _record(row: dict) -> list[dict]:
    """Every stored field of one row, as text, for the detail panel (collected data: shown as data, never markup)."""
    fields = []
    for name, value in row.items():
        local = to_local_datetime(value) if is_date_column(name) else value
        text = local.strftime(DISPLAY_FORMAT) if isinstance(local, datetime) else ("" if value is None else str(value))
        fields.append({"campo": name, "valor": text[:4000] + ("…" if len(text) > 4000 else "")})
    return fields


def table(rows, *, key: str, columns: dict | None = None, view: str | None = None, windowed: bool = True,
          detail: bool = True, on_pick=None, searchable: bool = True):
    """Searchable, sortable table. `view` names a table_views layout; selecting a row shows every stored field.

    `on_pick(row)` draws extra context for the selected row inside its detail panel; the row is also returned.
    """
    if not rows:
        empty("No hay datos para la ventana seleccionada.")
        return
    raw = [dict(row) for row in rows]
    if view:
        shown, config = present(raw, view), column_config(VIEWS[view]) | (columns or {})
        has_dates = any(column.kind == "date" for column in VIEWS[view])
    else:
        shown, date_columns = format_table_rows(visible(row) for row in raw)
        # Real datetimes (not text) so clicking a date column sorts chronologically
        config = {name: st.column_config.DatetimeColumn(format=COLUMN_FORMAT) for name in date_columns} | (columns or {})
        has_dates = bool(date_columns)
    available = list(pd.DataFrame(shown).columns)
    search = st.text_input("Buscar en la tabla", key=f"search-text-{key}", placeholder="Nombre, IP, ruta, estado…",
                           label_visibility="collapsed", icon=":material/search:") if searchable else ""
    matches = [index for index, row in enumerate(shown) if filter_table_rows([row], search, available)]
    frame = pd.DataFrame([shown[index] for index in matches], columns=available)
    if search:
        st.caption(f"{len(matches)} de {len(shown)} fila(s) coinciden con la búsqueda.")
    event = st.dataframe(frame, width="stretch", hide_index=True, column_config=config, key=f"table-{key}",
                         on_select="rerun" if detail else "ignore", selection_mode="single-row")
    caption = " ".join(text for text, show in (("Fechas en hora local del equipo.", has_dates),
                                               ("Seleccione una fila para ver todos sus campos.", detail)) if show)
    if caption:
        st.caption(caption)
    selected = list(getattr(getattr(event, "selection", None), "rows", None) or [])
    if detail and selected and selected[0] < len(matches):
        with st.container(border=True):
            st.markdown("**Detalle de la fila seleccionada**")
            record = raw[matches[selected[0]]]
            st.dataframe(pd.DataFrame(_record(record)), hide_index=True, width="stretch", key=f"record-{key}")
            shown_row = shown[matches[selected[0]]]
            search_links([value for name, value in list(record.items()) + list(shown_row.items())
                          if name in ENTITY_FIELDS], key=f"links-{key}")
            if on_pick:
                on_pick(record)
    else:
        record = None
    st.download_button("Descargar CSV", frame.to_csv(index=False).encode("utf-8"), csv_name(key, windowed), "text/csv",
                       key=f"download-{key}", icon=":material/download:",
                       help="Exporta las filas visibles, con el filtro de búsqueda aplicado.")
    return record


def severity_label(value: str) -> str:
    return f"{SEVERITY_ICONS.get(value, '⚪')} {value.upper()}"


def chart(figure, key: str | None = None):
    st.plotly_chart(figure, width="stretch", key=key,
                    config={"displaylogo": False, "responsive": True})


@st.dialog("Acerca de Atalaya")
def about_dialog():
    from shared.about import APP_NAME, APP_VERSION, AUTHOR, AUTHOR_LOGO_PATH, COMPANY_URL, COPYRIGHT, REPOSITORY_URL

    _, middle, _ = st.columns([1, 2, 1])
    if AUTHOR_LOGO_PATH.exists():
        middle.image(str(AUTHOR_LOGO_PATH), width="stretch")
    st.markdown(f'<div class="nl-about"><h3>{APP_NAME}</h3><small>v{APP_VERSION}</small><hr>'
                f'<p>Desarrollado por</p><b>{AUTHOR}</b></div>', unsafe_allow_html=True)
    # A link the user opens by hand: the application itself never connects to GitHub
    st.link_button("Repositorio en GitHub", REPOSITORY_URL, icon=":material/open_in_new:", width="stretch")
    st.link_button("Sitio web de LindeCode", COMPANY_URL, icon=":material/language:", width="stretch")
    st.caption(COPYRIGHT)
