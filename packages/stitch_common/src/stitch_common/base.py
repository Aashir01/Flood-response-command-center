"""Base class for every contract model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    """Immutable model that rejects unknown fields (``additionalProperties: false``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
