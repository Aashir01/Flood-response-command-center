"""Corpus manifest model and loader (design section 3.3, LIB-R1.4).

``data/demo/library/manifest.yaml`` is the single source of truth for every document, committed or
fetched. Every field below must be present (nullable fields may be ``null``); a missing field
fails ingestion and the license check.

Deviations from the design, recorded in ``docs/decisions.md``:
* ``format`` (``text`` or ``pdf``): committed documents are text-first renditions (UTF-8, pages
  separated by form feeds) of public-domain web pages or team-authored translations.
* ``sha256`` may be ``null`` only for ``tier: fetch`` entries not yet pinned; ``fetch_corpus.py``
  refuses them until ``--repin`` records a hash after a human looked at the file.
* ``owner_confirmed`` may be ``false`` on committed rows when the implementing agent verified the
  license itself; the checker warns, and ``--require-owner-confirmed`` turns that into a failure.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SLUG = r"^[a-z0-9][a-z0-9_-]{2,63}$"
DocType = Literal["guideline", "plan", "sitrep", "standard", "assessment", "digest", "translation"]


class ManifestError(ValueError):
    """The manifest is missing, unreadable or has an invalid entry."""


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str = Field(pattern=SLUG)
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    doc_type: DocType
    lang: Literal["en", "ur"]
    source_url: str = Field(pattern=r"^https://")
    retrieved_on: date | None
    as_of: date | None
    sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    license: str = Field(min_length=1)
    license_url: str | None
    license_evidence: str
    redistributable: bool
    owner_confirmed: bool
    tier: Literal["committed", "fetch"]
    path: str | None
    format: Literal["text", "pdf"]
    translation_of: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _tier_rules(self) -> ManifestEntry:
        if self.tier == "committed":
            if not self.path:
                raise ValueError("committed entries need a path")
            if self.sha256 is None:
                raise ValueError("committed entries need a sha256")
        elif self.path is not None:
            raise ValueError("fetch entries must not have a path")
        return self


def parse_manifest(data: object) -> list[ManifestEntry]:
    if not isinstance(data, list):
        raise ManifestError("manifest must be a YAML list of entries")
    out: list[ManifestEntry] = []
    seen: set[str] = set()
    for i, item in enumerate(data):
        try:
            entry = ManifestEntry.model_validate(item)
        except ValidationError as exc:
            fields = sorted({".".join(str(p) for p in e["loc"]) or "<entry>" for e in exc.errors()})
            raise ManifestError(
                f"manifest entry {i}: invalid or missing {', '.join(fields)}"
            ) from exc
        if entry.doc_id in seen:
            raise ManifestError(f"duplicate doc_id {entry.doc_id!r}")
        seen.add(entry.doc_id)
        out.append(entry)
    return out


def load_manifest(path: Path) -> list[ManifestEntry]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    return parse_manifest(data)
