# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.windows import explorer


def test_validates_only_existing_absolute_local_paths(tmp_path):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")

    assert explorer.validate_local_path(sample) == sample.resolve()
    for invalid in ("relative.exe", "https://example.test/a.exe", r"\\server\share\a.exe", tmp_path / "missing.exe"):
        with pytest.raises((OSError, ValueError)):
            explorer.validate_local_path(invalid)


def test_explorer_selects_file_without_executing_it(tmp_path, monkeypatch):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")
    fake_windows = tmp_path / "Windows"
    fake_windows.mkdir()
    (fake_windows / "explorer.exe").write_bytes(b"MZ")
    monkeypatch.setenv("WINDIR", str(fake_windows))
    calls = []

    result = explorer.open_in_explorer(sample, select_file=True,
                                       launcher=lambda args, shell: calls.append((args, shell)))

    assert result == sample.resolve()
    assert calls == [([str(fake_windows / "explorer.exe"), f"/select,{sample.resolve()}"], False)]


def test_open_directory_uses_parent_for_a_file(tmp_path, monkeypatch):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")
    fake_windows = tmp_path / "Windows"
    fake_windows.mkdir()
    (fake_windows / "explorer.exe").write_bytes(b"MZ")
    monkeypatch.setenv("WINDIR", str(fake_windows))
    calls = []

    explorer.open_in_explorer(sample, launcher=lambda args, shell: calls.append((args, shell)))

    assert calls == [([str(fake_windows / "explorer.exe"), str(tmp_path.resolve())], False)]
