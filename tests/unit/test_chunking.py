from pathlib import Path

from application.chunking import MarkdownChunker


def test_markdown_chunks_preserve_sections_and_code_blocks():
    text = "# Manual\n\nIntroducción.\n\n## Seguridad\n\n" + ("dato " * 200) + "\n\n```powershell\nGet-Service\n```"
    chunks = MarkdownChunker(max_chars=600, overlap_chars=50).chunk(Path("README.md"), text)
    assert chunks
    assert all(chunk.trust_level == "trusted" for chunk in chunks)
    assert any(chunk.section == "Seguridad" for chunk in chunks)
    assert "Get-Service" in "\n".join(chunk.content for chunk in chunks)
    assert len({chunk.chunk_key for chunk in chunks}) == len(chunks)

