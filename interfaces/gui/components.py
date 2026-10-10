from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import pandas as pd
import streamlit as st

from interfaces.gui.table_formatting import (COLUMN_FORMAT, DISPLAY_FORMAT, filter_table_rows, format_table_rows,
                                             is_date_column, to_local_datetime)
from interfaces.gui.table_views import VIEWS, column_config, present, visible
from shared.i18n import t, DEFAULT_LANGUAGE


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
[data-testid="stSidebarNav"] .stMarkdownBadge {
  background-color: #EF4444 !important; color: #FFFFFF !important;
  border-radius: 999px !important; padding: 1px 6px !important;
  font-size: 0.68rem !important; font-weight: 700 !important;
  vertical-align: middle !important; line-height: 1.2 !important;
  margin-left: 6px !important; display: inline-block !important;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25) !important;
}
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


PAGE_HERO_MAP: dict[str, str] = {
    "panel de seguridad": "overview",
    "en vivo": "live",
    "conexiones": "connections",
    "alertas": "alerts",
    "accesos": "access",
    "archivos": "files",
    "persistencia": "persistence",
    "firewall": "firewall",
    "informes": "reports",
    "chat": "chat",
    "ajustes": "settings",
    "primeros pasos": "getting_started",
    "procesos y ram": "processes",
    "buscar": "search",
    "historial de análisis": "history",
    "ia local": "local_ai",
}


def severity_name(level: str, lang: str = DEFAULT_LANGUAGE) -> str:
    name = t(f"tables.severity.{level}", lang=lang)
    return name if isinstance(name, str) else SEVERITY_NAMES.get(level, level)


def hero(title: str, subtitle: str, page_key: str | None = None, lang: str | None = None):
    """Page header. Only literals written in this codebase may be passed here (it renders HTML)."""
    if lang is None:
        lang = st.session_state.get("language") or DEFAULT_LANGUAGE

    if not page_key:
        normalized = "".join(c for c in title.lower() if c.isalnum() or c.isspace()).strip()
        for key, pkey in PAGE_HERO_MAP.items():
            if key in normalized:
                page_key = pkey
                break

    if page_key:
        title = t(f"pages.{page_key}.title", lang=lang, default=title)
        subtitle = t(f"pages.{page_key}.subtitle", lang=lang, default=subtitle)

    st.markdown(f'<div class="nl-hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def risk_banner(level: str, detail: str, lang: str | None = None):
    """`level` is validated against the known severities; `detail` must be a literal or a number."""
    if lang is None:
        lang = st.session_state.get("language") or DEFAULT_LANGUAGE
    level = level if level in SEVERITY_COLORS else "low"
    color = SEVERITY_COLORS[level]
    sev_name = t(f"tables.severity.{level}", lang=lang, default=SEVERITY_NAMES[level]).lower()
    risk_title = f"Risk: {sev_name}" if lang == "en" else f"Riesgo {sev_name}"
    st.markdown(
        f'<div class="nl-risk" style="background:{color}1f"><div class="dot" style="background:{color}"></div>'
        f'<div><b>{risk_title}</b><br><span>{detail}</span></div></div>',
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
          detail: bool = True, on_pick=None, searchable: bool = True, lang: str | None = None, dates=()):
    """Searchable, sortable table. `view` names a table_views layout; selecting a row shows every stored field.

    `on_pick(row)` draws extra context for the selected row inside its detail panel; the row is also returned.
    """
    if lang is None:
        lang = st.session_state.get("language") or DEFAULT_LANGUAGE
    if not rows:
        empty("No data for the selected time window." if lang == "en" else "No hay datos para la ventana seleccionada.")
        return
    raw = [dict(row) for row in rows]
    if view:
        shown, config = present(raw, view, lang=lang), column_config(VIEWS[view], lang=lang) | (columns or {})
        has_dates = any(column.kind == "date" for column in VIEWS[view])
        headers = t("tables.headers", lang=lang) if isinstance(t("tables.headers", lang=lang), dict) else {}
        date_columns = [headers.get(column.source, column.label) for column in VIEWS[view] if column.kind == "date"]
    else:
        shown, date_cols_res = format_table_rows((visible(row) for row in raw), dates)
        date_columns = list(date_cols_res)
        # Real datetimes (not text) so clicking a date column sorts chronologically
        config = {name: st.column_config.DatetimeColumn(format=COLUMN_FORMAT) for name in date_columns} | (columns or {})
        has_dates = bool(date_columns)
    available = list(pd.DataFrame(shown).columns)
    groupable = [c for c in available if c not in date_columns]

    search_placeholder = "Name, IP, path, status…" if lang == "en" else "Nombre, IP, ruta, estado…"
    search_label = "Search in table" if lang == "en" else "Buscar en la tabla"

    if searchable and groupable:
        col_search, col_group = st.columns([3, 2])
        search = col_search.text_input(search_label, key=f"search-text-{key}", placeholder=search_placeholder,
                                       label_visibility="collapsed", icon=":material/search:")
        group_options = ["none"] + groupable
        group_by = col_group.selectbox(
            t("tables.group_by", lang=lang, default="Agrupar por"),
            group_options,
            index=0,
            key=f"group-by-{key}",
            format_func=lambda c: t("tables.no_grouping", lang=lang, default="Sin agrupar (todas las filas)") if c == "none" else f"{t('tables.group_by', lang=lang, default='Agrupar por')}: {c}",
            label_visibility="collapsed",
        )
    elif searchable:
        search = st.text_input(search_label, key=f"search-text-{key}", placeholder=search_placeholder,
                               label_visibility="collapsed", icon=":material/search:")
        group_by = "none"
    elif groupable:
        group_options = ["none"] + groupable
        group_by = st.selectbox(
            t("tables.group_by", lang=lang, default="Agrupar por"),
            group_options,
            index=0,
            key=f"group-by-{key}",
            format_func=lambda c: t("tables.no_grouping", lang=lang, default="Sin agrupar (todas las filas)") if c == "none" else f"{t('tables.group_by', lang=lang, default='Agrupar por')}: {c}",
            label_visibility="collapsed",
        )
        search = ""
    else:
        search = ""
        group_by = "none"

    matches = [index for index, row in enumerate(shown) if filter_table_rows([row], search, available)]

    if group_by == "none":
        frame = pd.DataFrame([shown[index] for index in matches], columns=available)
        if search:
            st.caption(t("common.rows_matching", lang=lang, matches=len(matches), total=len(shown)))
        event = st.dataframe(frame, width="stretch", hide_index=True, column_config=config, key=f"table-{key}",
                             on_select="rerun" if detail else "ignore", selection_mode="single-row")
        date_note = "Dates in device local time." if lang == "en" else "Fechas en hora local del equipo."
        row_note = "Select a row to inspect all fields." if lang == "en" else "Seleccione una fila para ver todos sus campos."
        caption = " ".join(text for text, show in ((date_note, has_dates), (row_note, detail)) if show)
        if caption:
            st.caption(caption)
        selected = list(getattr(getattr(event, "selection", None), "rows", None) or [])
        if detail and selected and selected[0] < len(matches):
            with st.container(border=True):
                st.markdown("**Selected row details**" if lang == "en" else "**Detalle de la fila seleccionada**")
                record = raw[matches[selected[0]]]
                st.dataframe(pd.DataFrame(_record(record)), hide_index=True, width="stretch", key=f"record-{key}")
                shown_row = shown[matches[selected[0]]]
                search_links([value for name, value in list(record.items()) + list(shown_row.items())
                              if name in ENTITY_FIELDS], key=f"links-{key}")
                if on_pick:
                    on_pick(record)
        else:
            record = None
        csv_label = "Download CSV" if lang == "en" else "Descargar CSV"
        csv_help = "Exports visible rows with search filter applied." if lang == "en" else "Exporta las filas visibles, con el filtro de búsqueda aplicado."
        st.download_button(csv_label, frame.to_csv(index=False).encode("utf-8"), csv_name(key, windowed), "text/csv",
                           key=f"download-{key}", icon=":material/download:", help=csv_help)
        return record

    # Grouped view
    if search:
        st.caption(t("common.rows_matching", lang=lang, matches=len(matches), total=len(shown)))
    group_buckets = defaultdict(list)
    empty_label = "(vacío)" if lang == "es" else "(empty)"
    for idx in matches:
        val = shown[idx].get(group_by)
        val_display = empty_label if val is None or val == "" else str(val)
        group_buckets[val_display].append(idx)

    sorted_groups = sorted(group_buckets.items(), key=lambda item: len(item[1]), reverse=True)
    count_hdr = t("tables.count", lang=lang, default="Ocurrencias")
    first_seen_hdr = t("tables.first_seen", lang=lang, default="Primera vez")
    last_seen_hdr = t("tables.last_seen", lang=lang, default="Última vez")

    grouped_data = []
    primary_date_col = date_columns[0] if date_columns else None

    for g_val, g_indices in sorted_groups:
        entry = {
            group_by: g_val,
            count_hdr: len(g_indices),
        }
        if primary_date_col:
            dates_in_group = [shown[i].get(primary_date_col) for i in g_indices
                              if isinstance(shown[i].get(primary_date_col), datetime)]
            entry[first_seen_hdr] = min(dates_in_group) if dates_in_group else None
            entry[last_seen_hdr] = max(dates_in_group) if dates_in_group else None
        grouped_data.append(entry)

    group_cols = [group_by, count_hdr]
    if primary_date_col:
        group_cols.extend([first_seen_hdr, last_seen_hdr])

    group_frame = pd.DataFrame(grouped_data, columns=group_cols)
    group_config = {
        count_hdr: st.column_config.NumberColumn(count_hdr, format="%d"),
    }
    if primary_date_col:
        group_config[first_seen_hdr] = st.column_config.DatetimeColumn(first_seen_hdr, format=COLUMN_FORMAT)
        group_config[last_seen_hdr] = st.column_config.DatetimeColumn(last_seen_hdr, format=COLUMN_FORMAT)

    group_event = st.dataframe(group_frame, width="stretch", hide_index=True, column_config=group_config,
                               key=f"table-grouped-{key}", on_select="rerun", selection_mode="single-row")

    st.caption(t("tables.grouped_caption", lang=lang, groups=len(sorted_groups), matches=len(matches),
                 default=f"{len(sorted_groups)} grupos únicos de {len(matches)} filas coincidentes. Seleccione un grupo para ver sus eventos."))

    grp_selected = list(getattr(getattr(group_event, "selection", None), "rows", None) or [])
    record = None
    if grp_selected and grp_selected[0] < len(sorted_groups):
        picked_val, picked_indices = sorted_groups[grp_selected[0]]
        events_label = t("tables.group_events", lang=lang, default="Eventos de este grupo")
        with st.container(border=True):
            st.markdown(f"**{events_label}: `{plain_label(picked_val)}`** ({len(picked_indices)})")
            sub_frame = pd.DataFrame([shown[i] for i in picked_indices], columns=available)
            sub_event = st.dataframe(sub_frame, width="stretch", hide_index=True, column_config=config,
                                     key=f"table-sub-{key}", on_select="rerun" if detail else "ignore",
                                     selection_mode="single-row")
            sub_selected = list(getattr(getattr(sub_event, "selection", None), "rows", None) or [])
            if detail and sub_selected and sub_selected[0] < len(picked_indices):
                with st.container(border=True):
                    st.markdown("**Selected row details**" if lang == "en" else "**Detalle de la fila seleccionada**")
                    record = raw[picked_indices[sub_selected[0]]]
                    st.dataframe(pd.DataFrame(_record(record)), hide_index=True, width="stretch", key=f"record-grp-{key}")
                    sub_shown_row = shown[picked_indices[sub_selected[0]]]
                    search_links([value for name, value in list(record.items()) + list(sub_shown_row.items())
                                  if name in ENTITY_FIELDS], key=f"links-grp-{key}")
                    if on_pick:
                        on_pick(record)

    csv_label = "Download CSV" if lang == "en" else "Descargar CSV"
    csv_help = "Exports visible rows with search filter applied." if lang == "en" else "Exporta las filas visibles, con el filtro de búsqueda aplicado."
    st.download_button(csv_label, group_frame.to_csv(index=False).encode("utf-8"),
                       csv_name(f"{key}_grouped", windowed), "text/csv",
                       key=f"download-{key}", icon=":material/download:", help=csv_help)
    return record


def severity_label(value: str) -> str:
    return f"{SEVERITY_ICONS.get(value, '⚪')} {value.upper()}"


def chart(figure, key: str | None = None):
    st.plotly_chart(figure, width="stretch", key=key,
                    config={"displaylogo": False, "responsive": True})


def about_dialog(lang: str | None = None):
    if lang is None:
        lang = st.session_state.get("language") or DEFAULT_LANGUAGE
    title = "About Atalaya" if lang == "en" else "Acerca de Atalaya"

    @st.dialog(title)
    def _dialog():
        from shared.about import APP_NAME, APP_VERSION, AUTHOR, AUTHOR_LOGO_PATH, COMPANY_URL, COPYRIGHT, REPOSITORY_URL

        _, middle, _ = st.columns([1, 2, 1])
        if AUTHOR_LOGO_PATH.exists():
            middle.image(str(AUTHOR_LOGO_PATH), width="stretch")
        dev_label = "Developed by" if lang == "en" else "Desarrollado por"
        st.markdown(f'<div class="nl-about"><h3>{APP_NAME}</h3><small>v{APP_VERSION}</small><hr>'
                    f'<p>{dev_label}</p><b>{AUTHOR}</b></div>', unsafe_allow_html=True)
        # A link the user opens by hand: the application itself never connects to GitHub
        repo_label = "GitHub Repository" if lang == "en" else "Repositorio en GitHub"
        company_label = "LindeCode Website" if lang == "en" else "Sitio web de LindeCode"
        st.link_button(repo_label, REPOSITORY_URL, icon=":material/open_in_new:", width="stretch")
        st.link_button(company_label, COMPANY_URL, icon=":material/language:", width="stretch")
        st.caption(COPYRIGHT)

    _dialog()

