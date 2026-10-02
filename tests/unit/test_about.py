from __future__ import annotations

import pytest

from interfaces.cli import main
from shared.about import APP_VERSION, AUTHOR, AUTHOR_LOGO_PATH, ICON_PATH


def test_version_flag_shows_version_and_author(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert APP_VERSION in output and AUTHOR in output


def test_branding_assets_are_bundled():
    assert ICON_PATH.is_file() and AUTHOR_LOGO_PATH.is_file()
    assert ICON_PATH.with_suffix(".ico").is_file()
