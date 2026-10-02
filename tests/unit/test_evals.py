import json

from application.evals import RagEvalHarness
from domain.knowledge import RetrievedChunk


class Rag:
    def search(self, query, top_k, trust):
        return [RetrievedChunk(1, "manual.md", "Manual", "RDP", "Evento 1149", "trusted", 1.0)]


def test_eval_harness_scores_retrieval_and_injection_boundary(tmp_path):
    fixture = tmp_path / "eval.json"
    fixture.write_text(json.dumps([{"name": "rdp", "query": "RDP", "expected_terms": ["1149"]}]), encoding="utf-8")
    result = RagEvalHarness(Rag()).run(fixture)
    assert result["score"] == 1.0
    assert result["total"] == 2
