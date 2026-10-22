# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
import sys
from infrastructure.windows.file_locks import inspect_file_locks, terminate_lock_process


def test_free_file_returns_no_locks(tmp_path):
    test_file = tmp_path / "free_file.txt"
    test_file.write_text("sample content")
    locks = inspect_file_locks(test_file)
    assert locks == []


def test_locked_file_detects_current_python_process(tmp_path):
    if sys.platform != "win32":
        return
    test_file = tmp_path / "locked_file.txt"
    test_file.write_text("locking content")

    # Keep file open in this process
    with open(test_file, "r+") as f:
        locks = inspect_file_locks(test_file)
        assert len(locks) >= 1
        pids = [item["pid"] for item in locks]
        assert os.getpid() in pids
        current = next(item for item in locks if item["pid"] == os.getpid())
        assert current["name"].lower().startswith("python")
        assert current["app_type"] in ("Consola / Terminal", "Ventana principal", "Desconocido", "Proceso crítico")


def test_terminate_lock_process_protects_system_pids():
    ok, msg = terminate_lock_process(4)
    assert not ok
    assert "crítico del sistema" in msg

    ok, msg = terminate_lock_process(0)
    assert not ok
