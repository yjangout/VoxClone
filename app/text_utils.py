"""文本切分（TTS 长句拆块）。"""

from __future__ import annotations

import re

DEFAULT_MAX_CHARS = 200
_CLAUSE_RE = re.compile(r"[^。！？；，、.!?;,\n]+[。！？；，、.!?;,\n]*")


def split_text_for_tts(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current = ""
    for match in _CLAUSE_RE.finditer(text):
        clause = match.group(0)
        while len(clause) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(clause[:max_chars])
            clause = clause[max_chars:]
        if current and len(current) + len(clause) > max_chars:
            chunks.append(current)
            current = clause
        else:
            current += clause
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()]
