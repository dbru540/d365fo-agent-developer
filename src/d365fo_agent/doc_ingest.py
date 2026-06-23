"""Ingest D365 functional documentation into citeable chunks for the doc index.

Two sources, normalized to the same ``(style, text)`` paragraph stream then chunked:
* **MS Learn** — Markdown from the public MicrosoftDocs D365 F&O repo, cloned locally.
* **Internal specs** — Word ``.docx``. A ``.docx`` is a zip of XML, so we read
  ``word/document.xml`` and pull the ``<w:t>`` runs with the standard library — NO python-docx.

Standard library only (``zipfile``, ``xml.etree``, ``re``).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_VALID_PLATFORMS = {"d365fo", "ax2012", "both"}


@dataclass
class Chunk:
    doc_id: str       # stable id of the source document
    origin: str       # "mslearn" | "internal"
    platform: str     # "d365fo" | "ax2012" | "both"
    module: str       # functional module, e.g. "accounts-payable" ("" if unknown)
    title: str        # section heading (the chunk's local title)
    source_ref: str   # URL (mslearn) or file path (internal) — the citation
    ord: int          # chunk order within the document
    text: str         # indexed text (title line + body)

    def to_dict(self) -> dict:
        return asdict(self)


def _para_style(para: ElementTree.Element) -> str:
    ppr = para.find(f"{WORD_NS}pPr")
    if ppr is None:
        return "body"
    pstyle = ppr.find(f"{WORD_NS}pStyle")
    if pstyle is None:
        return "body"
    val = pstyle.get(f"{WORD_NS}val", "")
    return "heading" if val.lower().startswith("heading") else "body"


def extract_docx_paragraphs(path: str | Path) -> list[tuple[str, str]]:
    """``.docx`` -> ``[(style, text)]`` where style is 'heading' or 'body'. Stdlib only."""
    with zipfile.ZipFile(Path(path)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    root = ElementTree.fromstring(xml)
    out: list[tuple[str, str]] = []
    for para in root.iter(f"{WORD_NS}p"):
        text = "".join(node.text for node in para.iter(f"{WORD_NS}t") if node.text).strip()
        if text:
            out.append((_para_style(para), text))
    return out


def markdown_paragraphs(md: str) -> list[tuple[str, str]]:
    """Markdown -> ``[(style, text)]``. ATX headings become 'heading'; blank-line-separated
    runs of text become 'body' paragraphs."""
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        joined = " ".join(line.strip() for line in buf).strip()
        if joined:
            out.append(("body", joined))
        buf.clear()

    for line in md.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if m:
            flush()
            out.append(("heading", m.group(2).strip()))
        elif not line.strip():
            flush()
        else:
            buf.append(line)
    flush()
    return out


def chunk_paragraphs(
    paragraphs: list[tuple[str, str]], *, doc_id: str, origin: str, platform: str,
    module: str, source_ref: str, max_chars: int = 1500,
) -> list[Chunk]:
    """Group body paragraphs under the most recent heading into ``Chunk``s; split a section
    that exceeds ``max_chars``. The chunk text is the title line followed by the body."""
    if platform not in _VALID_PLATFORMS:
        import warnings
        warnings.warn(
            f"Unknown platform {platform!r}; expected one of {sorted(_VALID_PLATFORMS)}. "
            "Defaulting to 'd365fo'. Check your --platform argument.",
            stacklevel=2,
        )
        platform = "d365fo"
    chunks: list[Chunk] = []
    title = doc_id
    buf: list[str] = []
    ordn = 0

    def flush() -> None:
        nonlocal buf, ordn
        body = "\n".join(buf).strip()
        if body:
            text = f"{title}\n{body}" if title else body
            chunks.append(Chunk(doc_id, origin, platform, module, title, source_ref, ordn, text))
            ordn += 1
        buf = []

    for style, text in paragraphs:
        if style == "heading":
            flush()
            title = text
        else:
            # Flush the current buffer before adding this item when it would push
            # us over the limit — so the current item seeds the next chunk.
            if buf and sum(len(x) for x in buf) + len(text) > max_chars:
                flush()
            buf.append(text)
    flush()
    return chunks


def ingest_docx_file(
    path: str | Path, *, origin: str = "internal", platform: str = "d365fo", module: str = "",
) -> list[Chunk]:
    path = Path(path)
    paras = extract_docx_paragraphs(path)
    return chunk_paragraphs(
        paras, doc_id=path.stem, origin=origin, platform=platform,
        module=module, source_ref=str(path),
    )


def ingest_markdown_file(
    path: str | Path, *, source_ref: str, origin: str = "mslearn", platform: str = "d365fo",
    module: str = "", doc_id: str | None = None,
) -> list[Chunk]:
    path = Path(path)
    paras = markdown_paragraphs(path.read_text(encoding="utf-8", errors="ignore"))
    return chunk_paragraphs(
        paras, doc_id=doc_id or path.stem, origin=origin, platform=platform,
        module=module, source_ref=source_ref,
    )


def ingest_internal_dir(directory: str | Path, *, platform: str = "d365fo") -> Iterator[Chunk]:
    """Every ``*.docx`` under ``directory`` (recursive). Module = the file's parent folder name."""
    directory = Path(directory)
    for path in sorted(directory.rglob("*.docx")):
        if path.name.startswith("~$"):  # Word lock files
            continue
        module = path.parent.name if path.parent != directory else ""
        yield from ingest_docx_file(path, platform=platform, module=module)


def ingest_mslearn_dir(
    directory: str | Path, *, base_url: str | None = None, platform: str = "d365fo",
) -> Iterator[Chunk]:
    """Every ``*.md`` under ``directory`` (recursive). The citation is ``base_url`` + the
    posix relative path without the ``.md`` suffix; module = the top relative folder."""
    directory = Path(directory)
    for path in sorted(directory.rglob("*.md")):
        rel = path.relative_to(directory).as_posix()
        slug = rel[:-3] if rel.endswith(".md") else rel
        source_ref = f"{base_url.rstrip('/')}/{slug}" if base_url else str(path)
        module = path.relative_to(directory).parts[0] if len(path.relative_to(directory).parts) > 1 else ""
        yield from ingest_markdown_file(
            path, source_ref=source_ref, platform=platform, module=module, doc_id=slug,
        )
