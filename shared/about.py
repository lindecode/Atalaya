"""Application identity shown in the GUI "Acerca de" dialog and in `--version`."""
from __future__ import annotations

from pathlib import Path


APP_NAME = "Atalaya"
DISPLAY_NAME = "Atalaya by LindeCode"
APP_VERSION = "1.0.0"
AUTHOR = "LindeCode"
REPOSITORY_URL = "https://github.com/lindecode/Atalaya"
COMPANY_URL = "https://lindecode.cloud"
COPYRIGHT = f"© 2026 {AUTHOR}. Código bajo MPL-2.0; marcas no incluidas."

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ICON_PATH = ASSETS_DIR / "icon.png"
AUTHOR_LOGO_PATH = ASSETS_DIR / "lindecode.jpeg"
# Sidebar header per theme; regenerate with packaging\wordmark.py
WORDMARK_PATHS = {theme: ASSETS_DIR / f"wordmark-{theme}.png" for theme in ("dark", "light")}
