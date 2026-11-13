"""Read and normalize source data.

Corpus: Python Enhancement Proposals (reStructuredText, public domain / CC0).
PEP files have no physical pages, so each document is split *in order* into
"source units" of at least ``MIN_UNIT_CHARS`` normalized characters, cut only at
paragraph boundaries (GUIDE.md §1).  A unit plays the role of a page: its id is
``<document_id>#u<NN>`` and its number is stored in ``DocumentPage.page``.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .models import DocumentPage

MIN_UNIT_CHARS = 1500

# Header fields copied into metadata.  Author/e-mail fields are deliberately dropped.
HEADER_FIELDS = {"PEP", "Title", "Status", "Type", "Created", "Python-Version"}
_UNDERLINE = re.compile(r"^([=\-~^\"'`#*+])\1{2,}\s*$")


# --------------------------------------------------------------------------- PDF
def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract each physical page; keep its page number and source.

    Pages with no extractable text are kept with ``metadata['empty']=True`` so the
    caller can log them (OCR would be a separate step).  Not used by the PEP
    corpus but kept working for PDF sources.
    """
    from pypdf import PdfReader

    pages: list[DocumentPage] = []
    for number, page in enumerate(PdfReader(str(path)).pages, start=1):
        text = normalize_text(page.extract_text() or "")
        pages.append(DocumentPage(document_id, source, number, text,
                                  {"empty": not text.strip()}))
    return pages


# ----------------------------------------------------------------- normalization
def _strip_inline_rst(line: str) -> str:
    line = re.sub(r"`([^`<]+?)\s*<[^>]+>`__?", r"\1", line)           # `text <url>`_
    line = re.sub(r":[a-zA-Z:]+:`~?([^`]+)`", r"\1", line)            # :pep:`484`
    line = re.sub(r"``([^`]+)``", r"\1", line)                         # ``code``
    line = re.sub(r"(?<![\w`])`([^`]+)`_?(?![\w`])", r"\1", line)      # `ref`_
    return line


def normalize_text(text: str) -> str:
    """Normalize Unicode (NFC), line endings and whitespace; keep paragraph breaks.

    Leading indentation is kept (it carries code-block structure); trailing
    spaces are removed and runs of 3+ blank lines collapse to one blank line.
    """
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", "    ").replace(" ", " ")
    text = "".join(ch for ch in text if ch == "\n" or unicodedata.category(ch)[0] != "C")
    lines = [ln.rstrip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def canonical(text: str) -> str:
    """Comparison form used to verify evidence: lowercase, single spaces."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip().lower()


# ------------------------------------------------------------------ PEP parsing
@dataclass
class Paragraph:
    text: str
    section: str


def parse_pep(raw: str) -> tuple[dict[str, str], list[Paragraph], list[str]]:
    """Return (header, paragraphs with their section heading, log messages)."""
    log: list[str] = []
    lines = raw.replace("\r\n", "\n").split("\n")
    header: dict[str, str] = {}
    i, last_key = 0, None
    while i < len(lines) and lines[i].strip():
        m = re.match(r"^([A-Za-z\-]+):\s*(.*)$", lines[i])
        if m:
            last_key = m.group(1)
            header[last_key] = m.group(2).strip()
        elif last_key:  # continuation line
            header[last_key] += " " + lines[i].strip()
        i += 1
    header = {k: v for k, v in header.items() if k in HEADER_FIELDS}

    body = lines[i:]
    paragraphs: list[Paragraph] = []
    section = "Preamble"
    buf: list[str] = []

    def flush() -> None:
        if buf:
            text = normalize_text("\n".join(buf))
            if text:
                paragraphs.append(Paragraph(text, section))
            buf.clear()

    j = 0
    while j < len(body):
        line = body[j]
        nxt = body[j + 1] if j + 1 < len(body) else ""
        # heading = text line followed by an underline of the same-ish length
        if line.strip() and _UNDERLINE.match(nxt) and not _UNDERLINE.match(line):
            flush()
            section = _strip_inline_rst(line.strip())
            j += 2
            continue
        if _UNDERLINE.match(line):  # stray over-line
            j += 1
            continue
        stripped = line.strip()
        if stripped.startswith(".. "):
            flush()
            j += 1
            if "::" in stripped:
                # directive (code-block, note, ...): drop the directive line, keep its body
                while j < len(body) and body[j].strip().startswith(":"):  # directive options
                    j += 1
                continue
            # comment / link target / footnote: drop it and its indented continuation
            while j < len(body) and body[j].startswith(" ") and body[j].strip():
                j += 1
            continue
        if not line.strip():
            flush()
        else:
            buf.append(_strip_inline_rst(line))
        j += 1
    flush()

    # Drop the license boilerplate section; it is not content.
    kept = [p for p in paragraphs if p.section.lower() not in {"copyright", "footnotes", "references"}]
    dropped = len(paragraphs) - len(kept)
    if dropped:
        log.append(f"dropped {dropped} paragraph(s) in Copyright/Footnotes/References sections")
    return header, kept, log


def build_units(document_id: str, source: str, paragraphs: list[Paragraph],
                base_meta: dict, min_chars: int = MIN_UNIT_CHARS) -> list[DocumentPage]:
    """Group paragraphs in order into units of >= min_chars normalized characters.

    Each unit keeps the list of (paragraph text, section) so that structure-aware
    chunking can respect headings.  A short tail is merged into the previous unit.
    """
    groups: list[list[Paragraph]] = []
    cur: list[Paragraph] = []
    size = 0
    for p in paragraphs:
        cur.append(p)
        size += len(p.text) + 2
        if size >= min_chars:
            groups.append(cur)
            cur, size = [], 0
    if cur:
        if groups:
            groups[-1].extend(cur)
        else:
            groups.append(cur)

    units: list[DocumentPage] = []
    for n, group in enumerate(groups, start=1):
        text = "\n\n".join(p.text for p in group)
        meta = dict(base_meta)
        meta.update({
            "unit_id": f"{document_id}#u{n:02d}",
            "section": group[0].section,
            "paragraphs": [{"text": p.text, "section": p.section} for p in group],
            "n_chars": len(text),
        })
        units.append(DocumentPage(document_id, source, n, text, meta))
    return units


def load_pep(path: Path, source: str) -> tuple[list[DocumentPage], dict, list[str]]:
    raw = path.read_text(encoding="utf-8")
    header, paragraphs, log = parse_pep(raw)
    number = int(header["PEP"])
    document_id = f"pep-{number:04d}"
    base_meta = {
        "title": header.get("Title", ""),
        "pep_number": number,
        "pep_type": header.get("Type", ""),
        "status": header.get("Status", ""),
        # Missing in the source header (e.g. PEP 8, PEP 257) -> stored as "none", not guessed.
        "python_version": header.get("Python-Version", "none"),
        "created": header.get("Created", ""),
    }
    units = build_units(document_id, source, paragraphs, base_meta)
    return units, {"document_id": document_id, **base_meta}, log
