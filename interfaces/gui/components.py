from __future__ import annotations

import pandas as pd
import streamlit as st


SEVERITY_ICONS = {"low": "⚪", "medium": "🟡", "high": "🟠", "critical": "🔴"}


def empty(message: str):
    st.info(message)


def table(rows, *, key: str):
    if not rows:
        empty("No hay datos para la ventana seleccionada.")
        return
    frame = pd.DataFrame(rows)
    st.dataframe(frame, use_container_width=True, hide_index=True)
    st.download_button("Descargar CSV", frame.to_csv(index=False).encode("utf-8"), f"{key}.csv", "text/csv", key=f"download-{key}")


def severity_label(value: str) -> str:
    return f"{SEVERITY_ICONS.get(value, '⚪')} {value.upper()}"

