# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from ports.repositories import CollectionRepository


class StatusService:
    def __init__(self, repository: CollectionRepository):
        self.repository = repository

    def execute(self) -> dict[str, object]:
        self.repository.initialize()
        return self.repository.status()

