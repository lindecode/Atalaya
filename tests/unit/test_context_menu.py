# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys
from infrastructure.windows.context_menu import is_context_menu_registered, set_context_menu_registered


def test_context_menu_registration_cycle():
    if sys.platform != "win32":
        return

    # Enable Spanish
    ok, msg = set_context_menu_registered(True, lang="es")
    assert ok
    assert is_context_menu_registered() is True

    # Enable English (updates label)
    ok, msg = set_context_menu_registered(True, lang="en")
    assert ok
    assert is_context_menu_registered() is True
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\*\shell\AtalayaLockFinder") as k:
        label, _ = winreg.QueryValueEx(k, "")
        assert label == "Who is using this file? (Atalaya)"

    # Disable
    ok, msg = set_context_menu_registered(False)
    assert ok
    assert is_context_menu_registered() is False


def test_cli_parser_handles_context_menu_and_lock_inspect():
    from interfaces.cli import _parser
    parser = _parser()

    args = parser.parse_args(["context-menu", "--status"])
    assert args.command == "context-menu"
    assert args.status is True

    args = parser.parse_args(["lock-inspect", "test.txt", "--cli"])
    assert args.command == "lock-inspect"
    assert args.path == "test.txt"
    assert args.cli is True

