"""Markdown from the LLM, made safe to render.

Answers are shaped by collected data (file names, commands, titles) that an attacker can control, so the formatting
the model writes is kept but nothing in it may load or open something outside the computer:
- images are dropped: rendering ![](http://host/?data) would make the browser fetch that URL;
- links and bare URLs become inert text (the address stays visible, nothing is clickable);
- HTML is escaped by Streamlit (unsafe_allow_html stays off) and `$` is escaped so PowerShell text is not LaTeX.
Code blocks and inline code are left exactly as written.
"""
from __future__ import annotations

import re

CODE = re.compile(r"(```.*?(?:```|$)|`[^`\n]+`)", re.S)
IMAGE = re.compile(r"!\[([^\]]*)\]\s*(?:\([^)]*\)|\[[^\]]*\])")
LINK = re.compile(r"\[([^\]]+)\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")
REFERENCE = re.compile(r"(?m)^\s{0,3}\[[^\]]+\]:\s*\S+.*$")
AUTOLINK = re.compile(r"<((?:https?|ftp|file)://[^>\s]+|mailto:[^>\s]+)>", re.I)
URL = re.compile(r"(?<![\w/])((?:https?|ftp|file)://[^\s<>()`\]]+)", re.I)


def _inert(text: str) -> str:
    """A URL as inline code: visible and copyable, never a link."""
    return "`" + text.replace("`", "'") + "`"


def _prose(part: str, image_label: str) -> str:
    part = IMAGE.sub(lambda match: f"[{image_label}{': ' + match.group(1) if match.group(1) else ''}]", part)
    part = REFERENCE.sub("", part)
    # Links first become "text (url)" with the url already inert, so the bare-URL pass must skip inline code
    part = LINK.sub(lambda match: f"{match.group(1)} ({_inert(match.group(2))})", part)
    part = AUTOLINK.sub(lambda match: _inert(match.group(1)), part)
    pieces = CODE.split(part)
    pieces = [piece if index % 2 else URL.sub(lambda match: _inert(match.group(1)), piece).replace("$", "\\$")
              for index, piece in enumerate(pieces)]
    return "".join(pieces)


def safe_markdown(text: str | None, lang: str = "es") -> str:
    image_label = "image omitted" if lang == "en" else "imagen omitida"
    parts = CODE.split(text or "")
    return "".join(part if index % 2 else _prose(part, image_label) for index, part in enumerate(parts))
