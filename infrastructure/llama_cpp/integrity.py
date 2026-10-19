# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def verify_packaged_components(settings, role: str) -> None:
    """Verify packaged llama.cpp files when the build supplied a trusted manifest."""
    manifest_path = settings.project_dir / "COMPONENTS.sha256.json"
    if not manifest_path.is_file():
        return
    try:
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("El manifiesto de componentes de Atalaya no es válido") from exc
    targets = [settings.llama_cpp_executable,
               settings.llama_cpp_model_path if role == "chat" else settings.llama_cpp_embedding_model_path]
    for target in targets:
        try:
            relative = target.resolve().relative_to(settings.project_dir.resolve()).as_posix()
            expected = entries[relative].casefold()
        except (ValueError, KeyError, AttributeError) as exc:
            raise RuntimeError(f"El componente no figura en el manifiesto: {target}") from exc
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Falló la verificación de integridad: {relative}")
