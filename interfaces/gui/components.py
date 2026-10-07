from __future__ import annotations

import pandas as pd
import streamlit as st

from interfaces.gui.table_formatting import filter_table_rows, format_table_rows


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


def table(rows, *, key: str, columns: dict | None = None):
    if not rows:
        empty("No hay datos para la ventana seleccionada.")
        return
    formatted, date_columns = format_table_rows(rows)
    available = list(pd.DataFrame(formatted).columns)
    with st.expander("Buscar en esta tabla", icon=":material/search:"):
        selected = st.multiselect("Columnas", available, default=available, key=f"search-columns-{key}")
        search = st.text_input("Texto", key=f"search-text-{key}", placeholder="Nombre, IP, ruta, estado...")
    filtered = filter_table_rows(formatted, search, selected)
    frame = pd.DataFrame(filtered, columns=available)
    if search:
        st.caption(f"{len(filtered)} de {len(formatted)} fila(s) coinciden con la búsqueda.")
    if date_columns:
        st.caption("Las fechas se muestran como DD/MM/AAAA HH:MM:SS en la hora local del equipo.")
    st.dataframe(frame, width="stretch", hide_index=True, column_config=columns)
    st.download_button("Descargar CSV", frame.to_csv(index=False).encode("utf-8"), f"{key}.csv", "text/csv",
                       key=f"download-{key}", icon=":material/download:")


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
