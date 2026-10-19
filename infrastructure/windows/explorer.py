# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Open validated local paths in Windows Explorer without executing them."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def validate_local_path(raw_path: str | Path) -> Path:
    text = str(raw_path).strip().strip('"')
    if not text or "\0" in text or "://" in text or text.startswith(("\\\\", "//")):
        raise ValueError("La ruta debe ser local")
    candidate = Path(text)
    if not candidate.is_absolute():
        raise ValueError("La ruta debe ser absoluta")
    # Reject reparse/symbolic links in every existing component before resolving.
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        if current.exists() and current.is_symlink():
            raise ValueError("No se abren enlaces simbólicos")
    return candidate.resolve(strict=True)


def open_in_explorer(raw_path: str | Path, select_file: bool = False,
                     launcher=subprocess.Popen) -> Path:
    """Open a directory or select a file. Never launches the target file."""
    target = validate_local_path(raw_path)
    directory = target if target.is_dir() else target.parent
    explorer = Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"
    if not explorer.is_file():
        raise OSError("No se encontró Windows Explorer")
    args = [str(explorer), f"/select,{target}"] if select_file and target.is_file() else [str(explorer), str(directory)]
    launcher(args, shell=False)
    return target
