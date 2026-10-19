# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import os
from pathlib import Path


def normalized_windows_path(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))

