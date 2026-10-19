# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import secrets
from pathlib import Path


def key_path(settings, role: str) -> Path:
    if role not in {"chat", "embedding"}:
        raise ValueError("Rol de llama.cpp inválido")
    return settings.database_path.parent / "llama-cpp" / f"{role}.key"


def load_or_create_key(settings, role: str) -> str:
    path = key_path(settings, role)
    try:
        existing = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        existing = ""
    if len(existing) >= 32:
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(48)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(value, encoding="ascii")
    temporary.replace(path)
    return value
