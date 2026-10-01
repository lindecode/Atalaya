from __future__ import annotations

import os
from pathlib import Path


def normalized_windows_path(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))

