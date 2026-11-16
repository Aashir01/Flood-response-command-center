"""Sentence-packing chunker and chunk ids (design section 4.4). Pure.

Consecutive sentences of one page are packed into chunks of 150 to 700 characters (target about
450), never crossing a page and with no overlap. A trailing chunk under 150 characters merges into
the previous one when the total stays at or under 900. A chunk is ``text[start:end]``.

``chunk_id = "c_" + sha256(f"{doc_sha256}:{page}:{start}:{end}:{CHUNKER_VERSION}")[:20]`` so the
same input gives the same ids (LIB-R1.5, LIB-P7). Changing the chunker bumps the version.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from stitch_library.core.sentences import split_sentences

CHUNKER_VERSION = "1"
MIN_CHARS, TARGET_CHARS, MAX_CHARS, MERGE_LIMIT = 150, 450, 700, 900


@dataclass(frozen=True)
class ChunkSpan:
    start: int
    end: int


def chunk_id(doc_sha256: str, page: int, start: int, end: int) -> str:
    key = f"{doc_sha256}:{page}:{start}:{end}:{CHUNKER_VERSION}"
    return "c_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def pack_sentences(sentences: Sequence[tuple[int, int]]) -> list[ChunkSpan]:
    chunks: list[list[int]] = []  # [start, end]
    for s, e in sentences:
        if chunks:
            cs, ce = chunks[-1]
            if ce - cs < TARGET_CHARS and e - cs <= MAX_CHARS:
                chunks[-1][1] = e
                continue
        chunks.append([s, e])
    if len(chunks) >= 2:
        ls, le = chunks[-1]
        ps, _ = chunks[-2]
        if le - ls < MIN_CHARS and le - ps <= MERGE_LIMIT:
            chunks[-2][1] = le
            chunks.pop()
    return [ChunkSpan(s, e) for s, e in chunks]


def chunk_page(text: str) -> list[ChunkSpan]:
    return pack_sentences(split_sentences(text))
