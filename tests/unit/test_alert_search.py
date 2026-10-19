# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from interfaces.gui.page_views import _alert_matches


ALERT = {"rule_id": "R07", "severity": "high", "title": "Puerto remoto sospechoso",
         "entity": "203.0.113.8", "evidence": '{"process": "tool.exe", "port": 4444}',
         "status": "dismissed", "status_note": "Herramienta del laboratorio"}


def test_alert_search_covers_rule_title_entity_evidence_and_note():
    for term in ("r07", "PUERTO", "203.0.113.8", "tool.exe", "4444", "laboratorio", "dismissed"):
        assert _alert_matches(ALERT, term)
    assert not _alert_matches(ALERT, "ransomware")
