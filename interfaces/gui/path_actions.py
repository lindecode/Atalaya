# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reusable, human-triggered Explorer actions for collected path fields."""
from __future__ import annotations

import hashlib

import streamlit as st

from infrastructure.windows.explorer import open_in_explorer, validate_local_path


PATH_FIELDS = ("path", "process_path", "dest_path", "ruta")


def path_actions(record: dict, key: str, lang: str = "es") -> None:
    candidates = []
    for field in PATH_FIELDS:
        value = record.get(field)
        if value and str(value) not in candidates:
            candidates.append(str(value))
    available = []
    for raw in candidates:
        try:
            available.append((raw, validate_local_path(raw)))
        except (OSError, ValueError):
            continue
    if not available:
        return
    st.markdown("**Local paths**" if lang == "en" else "**Ubicaciones locales**")
    for raw, target in available:
        token = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]
        st.code(raw, language=None)
        left, right = st.columns(2)
        if target.is_file() and left.button("Show file" if lang == "en" else "Mostrar archivo",
                                            key=f"path-select-{key}-{token}", icon=":material/folder_open:"):
            try:
                open_in_explorer(target, select_file=True)
            except (OSError, ValueError) as exc:
                st.error(str(exc))
        if right.button("Open folder" if lang == "en" else "Abrir directorio",
                        key=f"path-open-{key}-{token}", icon=":material/folder:"):
            try:
                open_in_explorer(target)
            except (OSError, ValueError) as exc:
                st.error(str(exc))
