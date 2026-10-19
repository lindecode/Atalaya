# Copyright (c) 2026 LindeCode S.A.S.
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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

