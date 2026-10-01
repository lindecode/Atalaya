from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


CollectionStatus = Literal["ok", "partial", "skipped", "error"]


@dataclass(frozen=True, slots=True)
class NetworkConnection:
    ts: str
    source: str
    proto: str | None
    direction: str | None
    laddr: str | None
    lport: int | None
    raddr: str | None
    rport: int | None
    state: str | None
    pid: int | None
    process_name: str | None
    process_path: str | None
    process_user: str | None
    signed: bool | None = None


@dataclass(frozen=True, slots=True)
class AuthEvent:
    ts: str
    channel: str
    event_id: int
    record_id: int
    logon_type: int | None = None
    target_user: str | None = None
    source_ip: str | None = None
    source_host: str | None = None
    process_name: str | None = None
    status_code: str | None = None
    raw_xml: str | None = None


@dataclass(frozen=True, slots=True)
class FileEvent:
    ts: str
    source: str
    action: str
    path: str
    dest_path: str | None = None
    extension: str | None = None
    size: int | None = None
    sha256: str | None = None
    process_name: str | None = None
    dedup_key: str = ""


@dataclass(frozen=True, slots=True)
class PersistenceItem:
    first_seen: str
    last_seen: str
    kind: str
    location: str
    name: str | None
    command: str | None


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    now: str
    cursor: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CollectionResult:
    collector: str
    item_kind: Literal["connections", "auth_events", "file_events", "persistence_items"]
    items: tuple[Any, ...]
    status: CollectionStatus
    warnings: tuple[str, ...] = ()
    next_cursor: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    entity_type: str
    entity_id: int
    snapshot: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    ts: str
    rule_id: str
    severity: Literal["low", "medium", "high", "critical"]
    title: str
    entity: str
    summary: dict[str, Any]
    evidence: tuple[EvidenceRef, ...]
    window_key: str


@dataclass(frozen=True, slots=True)
class EvidenceView:
    auth_events: tuple[dict[str, Any], ...] = ()
    connections: tuple[dict[str, Any], ...] = ()
    file_events: tuple[dict[str, Any], ...] = ()
    firewall_events: tuple[dict[str, Any], ...] = ()
    persistence_items: tuple[dict[str, Any], ...] = ()
    baseline: frozenset[tuple[str, str]] = frozenset()
