from __future__ import annotations

import hashlib
import re
from pathlib import Path

from domain.knowledge import KnowledgeChunk, TrustLevel


HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


class MarkdownChunker:
    def __init__(self, max_chars: int = 2_800, overlap_chars: int = 300):
        if max_chars < 500 or overlap_chars < 0 or overlap_chars >= max_chars:
            raise ValueError("Configuración de chunks inválida")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk(self, path: Path, text: str, trust_level: TrustLevel = "trusted") -> list[KnowledgeChunk]:
        title = path.stem
        section = title
        blocks: list[tuple[str, str]] = []
        buffer: list[str] = []
        in_code = False
        for line in text.replace("\r\n", "\n").split("\n"):
            if line.startswith("```"):
                in_code = not in_code
            match = HEADING.match(line) if not in_code else None
            if match:
                if buffer and "\n".join(buffer).strip():
                    blocks.append((section, "\n".join(buffer).strip()))
                buffer = [line]
                section = match.group(2).strip()[:300]
                if match.group(1) == "#": title = section
            else:
                buffer.append(line)
        if buffer and "\n".join(buffer).strip():
            blocks.append((section, "\n".join(buffer).strip()))

        chunks: list[KnowledgeChunk] = []
        for block_section, block in blocks:
            pieces = self._split_block(block)
            previous_tail = ""
            for piece in pieces:
                content = (previous_tail + "\n\n" + piece).strip() if previous_tail else piece.strip()
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                key_material = f"{path.as_posix()}|{block_section}|{len(chunks)}|{digest}"
                chunks.append(KnowledgeChunk(
                    hashlib.sha256(key_material.encode("utf-8")).hexdigest(), path.as_posix(), title,
                    block_section, content, trust_level, digest,
                ))
                previous_tail = content[-self.overlap_chars:] if self.overlap_chars else ""
        return chunks

    def _split_block(self, block: str) -> list[str]:
        if len(block) <= self.max_chars: return [block]
        paragraphs = re.split(r"\n{2,}", block)
        pieces, current = [], ""
        for paragraph in paragraphs:
            if len(paragraph) > self.max_chars:
                if current: pieces.append(current); current = ""
                pieces.extend(paragraph[i:i + self.max_chars] for i in range(0, len(paragraph), self.max_chars))
            elif not current or len(current) + len(paragraph) + 2 <= self.max_chars:
                current = f"{current}\n\n{paragraph}".strip()
            else:
                pieces.append(current); current = paragraph
        if current: pieces.append(current)
        return pieces
