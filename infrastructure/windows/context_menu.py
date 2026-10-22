# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Windows Explorer context menu integration for file lock inspection."""
from __future__ import annotations

from pathlib import Path
import sys

MENU_VERB = "AtalayaLockFinder"
MENU_LABELS = {
    "es": "¿Quién usa este archivo? (Atalaya)",
    "en": "Who is using this file? (Atalaya)",
}
SUBKEYS = (r"Software\Classes\*\shell", r"Software\Classes\Directory\shell")


def resolve_language(lang: str | None = None) -> str:
    """Returns 'es' or 'en' based on argument, settings, or default 'es'."""
    if lang in ("es", "en"):
        return lang
    try:
        from settings import Settings
        settings_lang = Settings().language
        if settings_lang in ("es", "en"):
            return settings_lang
    except Exception:
        pass
    return "es"


def _python_executable() -> str:
    exe = Path(sys.executable)
    w_exe = exe.with_name("pythonw.exe")
    if w_exe.exists():
        return str(w_exe)
    return str(exe)


def _icon_path() -> str | None:
    from shared.about import PROJECT_DIR
    ico = PROJECT_DIR / "assets" / "icon.ico"
    if ico.exists():
        return str(ico)
    return None


def _main_py_path() -> str:
    from shared.about import PROJECT_DIR
    return str(PROJECT_DIR / "main.py")


def is_context_menu_registered() -> bool:
    """Checks whether the Atalaya lock inspector is registered in the Windows Explorer context menu."""
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\*\shell\{MENU_VERB}\command") as key:
            val, _ = winreg.QueryValueEx(key, "")
            return bool(val and "lock-inspect" in val)
    except OSError:
        return False


def set_context_menu_registered(enable: bool, lang: str | None = None) -> tuple[bool, str]:
    """Enables or disables the Windows Explorer context menu item in HKCU with the specified or active language."""
    if sys.platform != "win32":
        return False, "El menú contextual solo es compatible con Microsoft Windows."

    import winreg

    if enable:
        resolved_lang = resolve_language(lang)
        label = MENU_LABELS.get(resolved_lang, MENU_LABELS["es"])
        py_exe = _python_executable()
        main_py = _main_py_path()
        icon = _icon_path()
        command_str = f'"{py_exe}" "{main_py}" lock-inspect "%1"'

        try:
            for subkey_root in SUBKEYS:
                verb_path = rf"{subkey_root}\{MENU_VERB}"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, verb_path) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, label)
                    if icon:
                        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon)
                    with winreg.CreateKey(key, "command") as cmd_key:
                        winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, command_str)
            msg = ("Menú contextual de Atalaya activado en el Explorador de Windows."
                   if resolved_lang == "es" else
                   "Atalaya context menu enabled in Windows Explorer.")
            return True, msg
        except Exception as exc:
            return False, f"Error al registrar en el registro de Windows: {exc}"
    else:
        try:
            for subkey_root in SUBKEYS:
                verb_path = rf"{subkey_root}\{MENU_VERB}"
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{verb_path}\command")
                except FileNotFoundError:
                    pass
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, verb_path)
                except FileNotFoundError:
                    pass
            return True, "Menú contextual de Atalaya desactivado del Explorador de Windows."
        except Exception as exc:
            return False, f"Error al eliminar del registro de Windows: {exc}"
