# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from domain.models import AlertCandidate, EvidenceRef
from infrastructure.sqlite.queries import SQLiteQueryRepository
from infrastructure.sqlite.repositories import SQLiteRepository
from settings import Settings


NOW = datetime.now(timezone.utc)


def _alert(ts: str, path: str, key: str) -> AlertCandidate:
    return AlertCandidate(
        ts, "R05", "medium", "Archivo observado", "fixture.exe", {"source": "fixture"},
        (EvidenceRef("file_event", 1, {"id": 1, "path": path}),), key,
    )


def test_alert_path_search_reads_full_evidence_and_escapes_wildcards(tmp_path):
    settings = replace(Settings(), database_path=tmp_path / "alerts.db", reports_dir=tmp_path / "reports")
    repository = SQLiteRepository(settings)
    repository.initialize()
    recent_id, literal_id, old_id = repository.save_alerts([
        _alert(NOW.isoformat(), r"C:\Users\Ana\Downloads\rare_tool.exe", "recent"),
        _alert(NOW.isoformat(), r"C:\Samples\100%_safe.exe", "literal"),
        _alert((NOW - timedelta(days=3)).isoformat(), r"C:\Old\rare_tool.exe", "old"),
    ])
    query = SQLiteQueryRepository(settings)
    since = (NOW - timedelta(hours=24)).isoformat()

    assert query.alert_ids_by_path("rare_tool.exe", since) == [recent_id]
    assert query.alert_ids_by_path(r"C:\Users\Ana", since) == [recent_id]
    assert query.alert_ids_by_path("100%_safe.exe", since) == [literal_id]
    assert old_id not in query.alert_ids_by_path("rare_tool.exe", since)
    assert query.alert_paths([recent_id, literal_id]) == {
        recent_id: [r"C:\Users\Ana\Downloads\rare_tool.exe"],
        literal_id: [r"C:\Samples\100%_safe.exe"],
    }
    with pytest.raises(ValueError):
        query.alert_ids_by_path(" a ", since)
