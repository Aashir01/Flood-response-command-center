"""Ingestion unit tests (task 5): each unreadable reason, the reorder detector, PDF extraction
from small generated PDFs, the low-yield rule and manifest validation (LIB-R1.1 to R1.5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from library_strategies import entry
from pydantic import ValidationError

from stitch_library.ingest.manifest import ManifestEntry
from stitch_library.ingest.pdf import classify_page, pdf_pages
from stitch_library.ingest.pipeline import IngestError, ingest_document, ingest_pages

URDU = (
    "سیلاب کے دوران پینے کا صاف پانی دستیاب نہیں ہو سکتا۔ ہر شخص کے لیے روزانہ کم از کم ایک "
    "گیلن پانی ذخیرہ کریں اور اسے صاف برتن میں رکھیں۔ بچوں اور بزرگوں کو زیادہ پانی کی ضرورت ہو "
    "سکتی ہے۔"
)
ENGLISH = (
    "Store at least one gallon of water per person per day for several days, "
    "for drinking and sanitation."
)


def _pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF, one Helvetica text line per page (empty string: blank page)."""
    objs: list[bytes] = []
    n = len(pages)
    font_id = 3 + 2 * n
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    for i, text in enumerate(pages):
        content_id = 4 + 2 * i
        objs.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 9 Tf 20 700 Td ({esc}) Tj ET".encode() if text else b""
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_clean_english_and_urdu_pages_are_ok() -> None:
    en = classify_page(ENGLISH)
    assert (en.status, en.lang, en.reordered) == ("ok", "en", False)
    ur = classify_page(URDU)
    assert (ur.status, ur.lang, ur.reordered) == ("ok", "ur", False)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "empty"),
        ("Page 3 -- 12", "empty"),
        ("\ue000\ue001\ue002\ue003 " + ENGLISH + " \ue004\ue005\ue006", "garbled"),
        ("هذا نص عربي فقط بدون علامات أردية خاصة وهو طويل بما يكفي للاختبار", "other_script"),
    ],
)
def test_each_unreadable_reason(raw: str, reason: str) -> None:
    cls = classify_page(raw)
    assert (cls.status, cls.reason) == ("unreadable", reason)


def test_reversed_urdu_words_are_detected_and_restored() -> None:
    reversed_words = " ".join(w[::-1] for w in URDU.split(" "))
    cls = classify_page(reversed_words)
    assert cls.status == "ok" and cls.lang == "ur" and cls.reordered
    assert "پانی" in cls.text


def test_long_urdu_page_without_function_words_is_garbled() -> None:
    junk = " ".join(["ٹڈڑ ںےھ"] * 120)
    cls = classify_page(junk)
    assert (cls.status, cls.reason) == ("unreadable", "garbled")


def test_pdf_extraction_and_empty_page(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    path.write_bytes(_pdf([ENGLISH, ""]))
    pages = pdf_pages(path, isolate=False)
    assert len(pages) == 2
    assert "one gallon of water per person per day" in " ".join(pages[0].split())
    assert classify_page(pages[1]).reason == "empty"


def test_pdf_ingestion_records_unreadable_page_and_low_yield(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    data = _pdf([ENGLISH, ENGLISH.replace("water", "food"), ""])
    path.write_bytes(data)
    e = entry("pdf-doc", format="pdf")
    doc = ingest_document(e, data, file_path=path)
    assert doc.report.pages == 3 and doc.report.readable == 2
    assert doc.report.unreadable == {3: "empty"}
    assert all(c.page != 3 for c in doc.chunks)
    low = _pdf([ENGLISH, "", ""])
    path.write_bytes(low)
    with pytest.raises(IngestError, match="readable"):
        ingest_document(e, low, file_path=path)
    assert ingest_document(e, low, file_path=path, allow_low_yield=True).report.readable == 1


def test_hash_mismatch_fails_ingestion() -> None:
    e = entry("hash-doc", sha256="0" * 64)
    with pytest.raises(IngestError, match="sha256"):
        ingest_document(e, ENGLISH.encode())


def test_text_first_source_splits_on_page_markers() -> None:
    data = f"{ENGLISH}\n<<<page-break>>>\n{URDU}".encode()
    doc = ingest_document(entry("text-doc"), data)
    assert [p.lang for p in doc.pages] == ["en", "ur"]
    assert {c.page for c in doc.chunks} == {1, 2}


@pytest.mark.parametrize("missing", ["license", "source_url", "redistributable"])
def test_manifest_entry_missing_a_required_field_fails(missing: str) -> None:
    raw = entry("ok-doc").model_dump()
    del raw[missing]
    with pytest.raises(ValidationError):
        ManifestEntry.model_validate(raw)


def test_ingest_pages_is_deterministic() -> None:
    a = ingest_pages(entry("det-doc"), [ENGLISH, URDU], "f" * 64)
    b = ingest_pages(entry("det-doc"), [ENGLISH, URDU], "f" * 64)
    assert [c.chunk_id for c in a.chunks] == [c.chunk_id for c in b.chunks]
