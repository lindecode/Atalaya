# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TrustLevel = Literal["trusted", "derived", "untrusted", "llm_generated"]


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    chunk_key: str
    source_uri: str
    title: str
    section: str
    content: str
    trust_level: TrustLevel
    content_hash: str


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    id: int
    source_uri: str
    title: str
    section: str
    content: str
    trust_level: TrustLevel
    score: float

