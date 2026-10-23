# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Application identity shown in the GUI "Acerca de" dialog and in `--version`."""
from __future__ import annotations

from pathlib import Path


APP_NAME = "Atalaya"
DISPLAY_NAME = "Atalaya by LindeCode"
APP_VERSION = "1.0.1"
AUTHOR = "LindeCode"
REPOSITORY_URL = "https://github.com/lindecode/Atalaya"
COMPANY_URL = "https://lindecode.cloud"
COPYRIGHT = f"© 2026 {AUTHOR}. Código bajo MPL-2.0; marcas no incluidas."

PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_DIR / "assets"
ICON_PATH = ASSETS_DIR / "icon.png"
AUTHOR_LOGO_PATH = ASSETS_DIR / "lindecode.jpeg"
# Sidebar header per theme; regenerate with packaging\wordmark.py
WORDMARK_PATHS = {theme: ASSETS_DIR / f"wordmark-{theme}.png" for theme in ("dark", "light")}
