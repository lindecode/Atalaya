from __future__ import annotations

from dataclasses import replace

import pytest

from application.reputation import FileReputationService
from settings import Settings


class Clock:
    def now_iso(self): return "2026-10-02T12:00:00+00:00"


class Store:
    def __init__(self): self.saved = []
    def initialize(self): pass
    def save(self, result): self.saved.append(result)
    def latest(self, limit=100): return self.saved[-limit:]


class Signatures:
    def inspect(self, path): return {"status": "Valid", "valid": True, "subject": "Test Publisher"}


class Provider:
    name = "test-provider"
    def __init__(self, malicious=0): self.malicious = malicious; self.hashes = []
    def lookup_hash(self, sha256):
        self.hashes.append(sha256)
        return {"stats": {"malicious": self.malicious, "suspicious": 0, "undetected": 60}}


def service(tmp_path, provider=None):
    settings = replace(Settings(), project_dir=tmp_path, database_path=tmp_path / "test.db",
                       reputation_max_bytes=1024)
    return FileReputationService(Store(), Clock(), settings, Signatures(), provider)


def test_local_inspection_hashes_without_network(tmp_path):
    executable = tmp_path / "safe.exe"; executable.write_bytes(b"MZtest")
    result = service(tmp_path).inspect(executable)
    assert result.provider == "local"
    assert result.verdict == "unknown"
    assert result.local["signature"]["valid"] is True


def test_online_lookup_sends_only_sha256_and_scores_detection(tmp_path):
    executable = tmp_path / "bad.exe"; executable.write_bytes(b"MZbad")
    provider = Provider(malicious=12)
    result = service(tmp_path, provider).inspect(executable, online=True)
    assert provider.hashes == [result.sha256]
    assert result.path == str(executable.resolve())
    assert result.verdict == "malicious"


def test_rejects_non_executable_and_requires_provider(tmp_path):
    text = tmp_path / "notes.txt"; text.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="Tipo"):
        service(tmp_path).inspect(text)
    with pytest.raises(ValueError, match="VIRUSTOTAL"):
        service(tmp_path).lookup("a" * 64)
