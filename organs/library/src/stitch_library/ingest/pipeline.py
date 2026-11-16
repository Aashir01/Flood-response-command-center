"""Pages -> classified pages -> chunks (design sections 4.1 to 4.4, LIB-R1).

``ingest_document`` is deterministic: the same manifest entry and bytes give the same pages,
chunk ids and rows (LIB-P7). Unreadable pages are kept with their reason and never produce chunks
(LIB-P16). A document with under 60 % readable pages fails unless ``allow_low_yield``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from stitch_library.core.chunk import chunk_id, chunk_page
from stitch_library.core.lang import detect_lang
from stitch_library.core.normalize import search_text
from stitch_library.ingest.manifest import ManifestEntry
from stitch_library.ingest.pdf import classify_page, pdf_pages, text_pages
from stitch_library.store.base import ChunkRow, DocRow, PageRow, Tier

MIN_READABLE = 0.6


class IngestError(RuntimeError):
    """A document cannot be ingested (bad hash, low yield, unreadable file)."""


@dataclass
class DocReport:
    doc_id: str
    pages: int
    readable: int
    reordered: int
    chunks: int
    unreadable: dict[int, str] = field(default_factory=dict)

    @property
    def readable_ratio(self) -> float:
        return self.readable / self.pages if self.pages else 0.0


@dataclass
class IngestedDoc:
    doc: DocRow
    pages: list[PageRow]
    chunks: list[ChunkRow]
    report: DocReport


def doc_row(entry: ManifestEntry, sha: str, tier: Tier) -> DocRow:
    return DocRow(
        doc_id=entry.doc_id,
        title=entry.title,
        publisher=entry.publisher,
        doc_type=entry.doc_type,
        lang=entry.lang,
        source_url=entry.source_url,
        license=entry.license,
        redistributable=entry.redistributable,
        tier=tier,
        sha256=sha,
        as_of=entry.as_of,
    )


def text_sha(chunk_text: str) -> str:
    return hashlib.sha256(search_text(chunk_text).encode("utf-8")).hexdigest()[:16]


def ingest_pages(
    entry: ManifestEntry,
    raw_pages: list[str],
    sha: str,
    *,
    tier: Tier = "committed",
    allow_low_yield: bool = False,
) -> IngestedDoc:
    pages: list[PageRow] = []
    chunks: list[ChunkRow] = []
    report = DocReport(entry.doc_id, len(raw_pages), 0, 0, 0)
    for n, raw in enumerate(raw_pages, start=1):
        cls = classify_page(raw)
        if cls.status != "ok":
            pages.append(PageRow(entry.doc_id, n, cls.lang, "unreadable", cls.reason, cls.text))
            report.unreadable[n] = str(cls.reason)
            continue
        report.readable += 1
        report.reordered += int(cls.reordered)
        pages.append(PageRow(entry.doc_id, n, cls.lang, "ok", None, cls.text))
        for span in chunk_page(cls.text):
            body = cls.text[span.start : span.end]
            lang = detect_lang(body)
            chunks.append(
                ChunkRow(
                    chunk_id=chunk_id(sha, n, span.start, span.end),
                    doc_id=entry.doc_id,
                    page=n,
                    start=span.start,
                    end=span.end,
                    lang=lang if lang in ("en", "ur") else cls.lang,
                    text=body,
                    search_text=search_text(body),
                    text_sha=text_sha(body),
                )
            )
    report.chunks = len(chunks)
    if not allow_low_yield and report.readable_ratio < MIN_READABLE:
        raise IngestError(
            f"{entry.doc_id}: only {report.readable}/{report.pages} pages are readable "
            f"(< {MIN_READABLE:.0%}); fix the source or pass --allow-low-yield"
        )
    return IngestedDoc(doc_row(entry, sha, tier), pages, chunks, report)


def ingest_document(
    entry: ManifestEntry,
    data: bytes,
    *,
    tier: Tier = "committed",
    allow_low_yield: bool = False,
    file_path: Path | None = None,
) -> IngestedDoc:
    if entry.format == "text":
        data = data.replace(b"\r\n", b"\n")  # checkout line endings must not change the hash
    sha = hashlib.sha256(data).hexdigest()
    if entry.sha256 is not None and sha != entry.sha256:
        raise IngestError(
            f"{entry.doc_id}: sha256 {sha} does not match the manifest {entry.sha256}"
        )
    if entry.format == "text":
        raw_pages = text_pages(data)
    else:
        if file_path is None:
            raise IngestError(f"{entry.doc_id}: PDF ingestion needs the file path")
        try:
            raw_pages = pdf_pages(file_path)
        except Exception as exc:
            raise IngestError(f"{entry.doc_id}: PDF extraction failed ({exc})") from exc
    return ingest_pages(entry, raw_pages, sha, tier=tier, allow_low_yield=allow_low_yield)
