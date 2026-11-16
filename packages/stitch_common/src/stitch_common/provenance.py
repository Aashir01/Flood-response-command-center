"""Provenance attached to every tool result, and the canonical input hash."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field

from stitch_common.base import Contract
from stitch_common.types import Mode, OrganName
from stitch_common.version import CONTRACT_VERSION

SHA256_PATTERN = r"^[0-9a-f]{64}$"
UUID4_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


class DataSource(Contract):
    id: str
    name: str
    license: str
    as_of: date | None


class ModelInfo(Contract):
    name: str
    version: str
    sha256: str


class Provenance(Contract):
    organ: OrganName
    tool: str
    tool_version: str
    contract_version: str
    run_id: str = Field(pattern=UUID4_PATTERN)
    inputs_hash: str = Field(pattern=SHA256_PATTERN)
    mode: Mode
    data_sources: list[DataSource]
    model: ModelInfo | None
    # v0.4: organs that use several models (Library: embedder, reranker, LLM) list them here.
    # ``model`` stays the primary model (or null). Absent means [].
    models: list[ModelInfo] = Field(default_factory=list)
    generated_at: AwareDatetime


def canonical_json(obj: Any) -> str:
    """Canonical JSON: sorted keys, no whitespace, UTF-8 characters kept as is."""
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def inputs_hash(obj: Any) -> str:
    """sha256 of the canonical JSON of ``obj`` (BOOT-P2: key-order invariant)."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def build_provenance(
    *,
    organ: OrganName,
    tool: str,
    tool_version: str,
    inputs: Any,
    mode: Mode,
    data_sources: Sequence[DataSource] = (),
    model: ModelInfo | None = None,
    run_id: str | None = None,
    models: Sequence[ModelInfo] = (),
    generated_at: datetime | None = None,
) -> Provenance:
    """Build a ``Provenance``. ``run_id`` defaults to a fresh uuid4, time to now (UTC).

    ``models`` (v0.4) lists every model the tool used; empty by default.
    """
    return Provenance(
        organ=organ,
        tool=tool,
        tool_version=tool_version,
        contract_version=CONTRACT_VERSION,
        run_id=run_id or str(uuid.uuid4()),
        inputs_hash=inputs_hash(inputs),
        mode=mode,
        data_sources=list(data_sources),
        model=model,
        models=list(models),
        generated_at=generated_at or datetime.now(UTC),
    )
