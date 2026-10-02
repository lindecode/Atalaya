"""Application identity shown in the GUI "Acerca de" dialog and in `--version`."""
from __future__ import annotations

from pathlib import Path


APP_NAME = "Atalaya"
APP_VERSION = "1.0.0"
AUTHOR = "LindeCode"
REPOSITORY_URL = "https://github.com/lindecode/Atalaya"
COPYRIGHT = f"© 2026 {AUTHOR}. Todos los derechos reservados."

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ICON_PATH = ASSETS_DIR / "icon.png"
AUTHOR_LOGO_PATH = ASSETS_DIR / "lindecode.jpeg"
