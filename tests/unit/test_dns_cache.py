from __future__ import annotations

from infrastructure.windows.dns_cache import names_for


RECORDS = [
    {"Entry": "www.example.com", "Data": "edge.example.net", "Type": 5},
    {"Entry": "edge.example.net", "Data": "203.0.113.7", "Type": 1},
    {"Entry": "other.example.org", "Data": "203.0.113.70", "Type": 1},
    {"Entry": "v6.example.net", "Data": "2001:DB8::1", "Type": 28},
]


def test_names_include_the_resolved_host_and_its_aliases_but_not_similar_ips():
    assert names_for("203.0.113.7", RECORDS) == ["edge.example.net", "www.example.com"]
    assert names_for("2001:db8::1", RECORDS) == ["v6.example.net"]
    assert names_for("198.51.100.1", RECORDS) == []
