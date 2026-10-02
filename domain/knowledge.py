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

