# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from typing import Any, Protocol


class StructuredAnalyzer(Protocol):
    model: str
    def analyze(self, alerts: list[dict[str, Any]]) -> tuple[dict[str, Any], int, list[int]]:
        """Returns (validated result, prompt chars, ids of the alerts actually sent to the model)."""
        ...


class ModelCatalog(Protocol):
    def list_models(self) -> list[dict[str, Any]]: ...
