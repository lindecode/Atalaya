from __future__ import annotations

from dataclasses import replace

from application.rag import RagService
from infrastructure.sqlite.knowledge_store import SQLiteKnowledgeStore
from ports.clock import Clock
from settings import Settings


class FixedClock:
    def now_iso(self): return "2026-10-02T12:00:00+00:00"


class FakeEmbedder:
    model = "fake-embed-v1"
    def __init__(self): self.calls = []
    def embed(self, texts):
        self.calls.append(list(texts))
        return [[1.0, float("rdp" in text.casefold())] for text in texts]


def test_secure_hybrid_index_cache_and_retrieval(tmp_path):
    document = tmp_path / "README.md"
    document.write_text("# Runbook\n\n## RDP\n\nInvestigue el evento 1149 y cite la evidencia.\n\n## Firewall\n\nRevise paquetes DROP.", encoding="utf-8")
    settings = replace(Settings(), project_dir=tmp_path, database_path=tmp_path / "rag.db",
                       reports_dir=tmp_path / "reports", rag_chunk_chars=600, rag_chunk_overlap_chars=50)
    embedder = FakeEmbedder()
    service = RagService(SQLiteKnowledgeStore(settings), FixedClock(), settings, embedder)

    first = service.index([document])
    second = service.index([document])
    results = service.search("cómo investigar RDP", 3)

    assert first["embedded"] == first["chunks"]
    assert second["embedded"] == second["chunks"]
    assert len(embedder.calls) == 2  # first document and query; second index reuses cached vectors
    assert results and results[0].trust_level == "trusted"
    assert "RDP" in results[0].content
    assert service.status()["queries_audited"] == 1


def test_index_rejects_document_outside_project(tmp_path):
    project = tmp_path / "project"; project.mkdir()
    outside = tmp_path / "outside.md"; outside.write_text("# no", encoding="utf-8")
    settings = replace(Settings(), project_dir=project, database_path=project / "rag.db")
    service = RagService(SQLiteKnowledgeStore(settings), FixedClock(), settings, None)
    try:
        service.index([outside])
    except ValueError as exc:
        assert "dentro del proyecto" in str(exc)
    else:
        raise AssertionError("Debió rechazar el documento externo")


def test_default_index_follows_moved_docs_and_drops_stale_sources(tmp_path):
    settings = replace(Settings(), project_dir=tmp_path, database_path=tmp_path / "rag.db", reports_dir=tmp_path / "reports")
    service = RagService(SQLiteKnowledgeStore(settings), FixedClock(), settings, None)
    (tmp_path / "README.md").write_text("# Guia\n\n## RDP\n\nEvento 1149.", encoding="utf-8")
    assert service.index()["sources"] == 1

    # The docs move into README/ (the case that crashed the installer) and a missing file is not an error
    (tmp_path / "README").mkdir()
    (tmp_path / "README.md").rename(tmp_path / "README" / "README.md")
    (tmp_path / "agente.md").write_text("# Plan\n\nFases.", encoding="utf-8")
    result = service.index()

    assert result["sources"] == 2
    assert result["removed_sources"] == ["README.md"]
    assert {item.source_uri for item in service.search("evento 1149 RDP", 5)} == {"README/README.md"}


def test_index_reports_missing_explicit_paths(tmp_path):
    settings = replace(Settings(), project_dir=tmp_path, database_path=tmp_path / "rag.db")
    service = RagService(SQLiteKnowledgeStore(settings), FixedClock(), settings, None)
    try:
        service.index([tmp_path / "no-existe.md"])
    except ValueError as exc:
        assert "No existe" in str(exc)
    else:
        raise AssertionError("Debió avisar del archivo inexistente")
