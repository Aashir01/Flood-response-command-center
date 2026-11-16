"""``ToolResult`` envelope and its only constructors, ``ok`` and ``fail``."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from stitch_common.base import Contract
from stitch_common.provenance import Provenance
from stitch_common.types import ErrorCode


class ErrorInfo(Contract):
    code: ErrorCode
    message: str
    retryable: bool


class ToolResult[T](Contract):
    """Every tool returns this.

    Invariant (BOOT-P1): ``ok`` iff ``data`` is set and ``error`` is not.

    When ``ok`` is false, ``error`` is required and ``data`` must be null.
    """

    ok: bool
    data: T | None
    error: ErrorInfo | None
    provenance: Provenance
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> ToolResult[T]:
        if self.ok:
            if self.data is None or self.error is not None:
                raise ValueError("ok=true requires data != null and error == null")
        elif self.data is not None or self.error is None:
            raise ValueError("ok=false requires data == null and error != null")
        return self


def ok[T](data: T, provenance: Provenance, warnings: list[str] | None = None) -> ToolResult[T]:
    """Build a successful envelope."""
    return ToolResult[T](
        ok=True, data=data, error=None, provenance=provenance, warnings=list(warnings or [])
    )


def fail(
    code: ErrorCode,
    message: str,
    retryable: bool,
    provenance: Provenance,
    warnings: list[str] | None = None,
) -> ToolResult[Any]:
    """Build a failed envelope. Domain failures are returned, never raised."""
    return ToolResult[Any](
        ok=False,
        data=None,
        error=ErrorInfo(code=code, message=message, retryable=retryable),
        provenance=provenance,
        warnings=list(warnings or []),
    )
