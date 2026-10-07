from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from infrastructure.reputation import virustotal
from infrastructure.reputation.virustotal import VirusTotalHashProvider


SHA = "a" * 64


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def _raises(exc):
    def fake(*_, **__): raise exc
    return fake


def test_requires_key_and_valid_hash_before_any_request(monkeypatch):
    monkeypatch.setattr(virustotal, "urlopen", lambda *a, **k: pytest.fail("no request expected"))
    with pytest.raises(ValueError):
        VirusTotalHashProvider("")
    with pytest.raises(ValueError, match="SHA-256"):
        VirusTotalHashProvider("key").lookup_hash("../files/" + SHA)


def test_sends_only_the_hash_and_parses_the_verdict(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen.update(url=request.full_url, key=request.get_header("X-apikey"), timeout=timeout, data=request.data)
        body = {"data": {"attributes": {"last_analysis_stats": {"malicious": 3, "harmless": "2"},
                                        "reputation": -5, "meaningful_name": "x.exe"}}}
        return Response(json.dumps(body).encode())
    monkeypatch.setattr(virustotal, "urlopen", fake_urlopen)

    result = VirusTotalHashProvider("key", timeout=3).lookup_hash(SHA.upper())

    assert seen == {"url": f"https://www.virustotal.com/api/v3/files/{SHA}", "key": "key", "timeout": 3, "data": None}
    assert result["stats"] == {"malicious": 3, "suspicious": 0, "undetected": 0, "harmless": 2}
    assert result["reputation"] == -5 and result["meaningful_name"] == "x.exe"


def test_unknown_hash_is_none_and_other_failures_are_runtime_errors(monkeypatch):
    provider = VirusTotalHashProvider("key")
    monkeypatch.setattr(virustotal, "urlopen", _raises(HTTPError("u", 404, "nf", {}, None)))
    assert provider.lookup_hash(SHA) is None
    monkeypatch.setattr(virustotal, "urlopen", _raises(HTTPError("u", 429, "quota", {}, None)))
    with pytest.raises(RuntimeError, match="429"):
        provider.lookup_hash(SHA)
    monkeypatch.setattr(virustotal, "urlopen", _raises(URLError("offline")))
    with pytest.raises(RuntimeError, match="no disponible"):
        provider.lookup_hash(SHA)
