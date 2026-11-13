"""Fixed-size and structure-aware chunking.  Chunks never cross a unit ("page")."""
from __future__ import annotations

import re

from .models import Chunk, DocumentPage

# Metadata copied from the unit onto every chunk (``paragraphs`` is internal only).
_UNIT_KEYS = ("title", "pep_number", "pep_type", "status", "python_version", "unit_id")


def _base_meta(page: DocumentPage) -> dict:
    return {k: page.metadata[k] for k in _UNIT_KEYS if k in page.metadata}


def _section_at(page: DocumentPage, offset: int) -> str:
    """Section heading of the paragraph that contains character ``offset``."""
    pos = 0
    section = page.metadata.get("section", "")
    for para in page.metadata.get("paragraphs", []):
        if pos > offset:
            break
        section = para["section"]
        pos += len(para["text"]) + 2  # "\n\n" separator used in build_units
    return section


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Character windows of ``size`` with ``overlap``; ignores sentence/heading boundaries."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    text = page.text
    chunks: list[Chunk] = []
    step = size - overlap
    start, n = 0, 0
    while start < len(text):
        piece = text[start:start + size]
        if piece.strip():
            meta = _base_meta(page)
            meta.update({"section": _section_at(page, start), "char_start": start,
                         "char_end": start + len(piece)})
            chunks.append(Chunk(f"{page.metadata['unit_id']}:A{n:03d}", page.document_id,
                                page.source, page.page, piece, meta))
            n += 1
        if start + size >= len(text):
            break
        start += step
    return chunks


_SENT_SPLIT = re.compile(r"(?<=[.!?:])\s+(?=[A-Z(\"'`])")


def _split_long(text: str, max_size: int) -> list[str]:
    """Split an oversized paragraph at sentence (then line, then hard) boundaries."""
    if len(text) <= max_size:
        return [text]
    parts = _SENT_SPLIT.split(text)
    joiner = " "
    if len(parts) == 1:
        parts, joiner = text.split("\n"), "\n"
    out: list[str] = []
    cur = ""
    for part in parts:
        while len(part) > max_size:  # last resort: hard cut
            if cur:
                out.append(cur)
                cur = ""
            out.append(part[:max_size])
            part = part[max_size:]
        if cur and len(cur) + 1 + len(part) > max_size:
            out.append(cur)
            cur = part
        else:
            cur = f"{cur}{joiner}{part}" if cur else part
    if cur:
        out.append(cur)
    return out


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Group consecutive paragraphs *of the same section* up to ``max_size`` chars.

    A new heading always starts a new chunk; oversized paragraphs are split at
    sentence boundaries.  Section metadata comes from the source heading.
    """
    groups: list[tuple[str, list[str]]] = []
    for para in page.metadata.get("paragraphs", [{"text": page.text, "section": ""}]):
        for piece in _split_long(para["text"], max_size):
            if groups and groups[-1][0] == para["section"] and \
                    sum(len(t) + 2 for t in groups[-1][1]) + len(piece) <= max_size:
                groups[-1][1].append(piece)
            else:
                groups.append((para["section"], [piece]))
    chunks: list[Chunk] = []
    for n, (section, texts) in enumerate(groups):
        meta = _base_meta(page)
        meta["section"] = section
        chunks.append(Chunk(f"{page.metadata['unit_id']}:B{n:03d}", page.document_id,
                            page.source, page.page, "\n\n".join(texts), meta))
    return chunks
