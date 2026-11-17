"""Run an organ's pure core function and wrap the outcome in a ``ToolResult`` envelope.

This module has no MCP dependency, so core logic and its tests stay independent of the SDK.
Cores return the output model (or an ``Outcome`` when they also report warnings, data sources or
the model used) and raise ``ToolFailure`` for domain failures. Anything else becomes an
``INTERNAL`` failure; details go to the log, not to the client.
"""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from stitch_common.envelope import ToolResult, fail, ok
from stitch_common.logging import get_logger
from stitch_common.organs import ORGAN_TOOLS
from stitch_common.provenance import DataSource, ModelInfo, build_provenance
from stitch_common.types import ErrorCode, Mode, OrganName


class ToolFailure(Exception):
    """Raised by core code for an expected, reportable failure (e.g. ``INFEASIBLE``)."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        retryable: bool = False,
        warnings: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message
        self.retryable = retryable
        # Envelope warnings that also apply to a failed result (e.g. the Voice's Urdu notice).
        self.warnings: list[str] = list(warnings or [])


@dataclass
class Outcome[T]:
    """A core result plus provenance details."""

    data: T
    warnings: list[str] = field(default_factory=list)
    data_sources: Sequence[DataSource] = ()
    model: ModelInfo | None = None
    # Set by cores whose results are looked up later by `provenance.run_id` (the Ledger's
    # `sensitivity_report`). Default: `run_tool` generates a fresh uuid4.
    run_id: str | None = None
    # The mode the core actually used (contract v0.4: "every result states which one it used").
    # Default: `current_mode()` from `STITCH_MODE`.
    mode: Mode | None = None
    # Contract v0.4 `Provenance.models`: every model the core used (Library: embedder,
    # reranker, LLM). `model` stays the primary one. Default: none.
    models: Sequence[ModelInfo] = ()


def current_mode() -> Mode:
    """``STITCH_MODE`` (``demo`` or ``live``); anything else means ``demo``."""
    return "live" if os.environ.get("STITCH_MODE", "demo").strip().lower() == "live" else "demo"


def _field_names(exc: ValidationError) -> str:
    names = sorted({".".join(str(p) for p in e["loc"]) or "<root>" for e in exc.errors()})
    return ", ".join(names)


async def run_tool(
    organ: OrganName,
    tool: str,
    tool_version: str,
    core: Callable[[Any], Any],
    arguments: Mapping[str, Any],
) -> ToolResult[Any]:
    """Validate ``arguments``, call ``core`` and return the envelope. Never raises."""
    spec = ORGAN_TOOLS[organ][tool]
    mode = current_mode()
    log = get_logger(f"stitch.{organ}")
    try:
        params = spec.input.model_validate(dict(arguments))
    except ValidationError as exc:
        prov = build_provenance(
            organ=organ, tool=tool, tool_version=tool_version, inputs=dict(arguments), mode=mode
        )
        return fail("INVALID_INPUT", f"invalid arguments: {_field_names(exc)}", False, prov)

    def prov_for(outcome: Outcome[Any] | None = None) -> Any:
        return build_provenance(
            organ=organ,
            tool=tool,
            tool_version=tool_version,
            inputs=params,
            mode=(outcome.mode if outcome and outcome.mode else mode),
            data_sources=outcome.data_sources if outcome else (),
            model=outcome.model if outcome else None,
            run_id=outcome.run_id if outcome else None,
            models=outcome.models if outcome else (),
        )

    try:
        if inspect.iscoroutinefunction(core):
            raw = await core(params)
        else:
            raw = await asyncio.to_thread(core, params)
        outcome: Outcome[Any] = raw if isinstance(raw, Outcome) else Outcome(raw)
        data = outcome.data
        if not isinstance(data, spec.output):
            data = spec.output.model_validate(data)
        return ok(data, prov_for(outcome), outcome.warnings)
    except ToolFailure as f:
        return fail(f.code, f.message, f.retryable, prov_for(), f.warnings)
    except NotImplementedError:
        return fail("INTERNAL", f"{organ}.{tool} is not implemented yet", False, prov_for())
    except ValidationError:
        log.exception("core returned an invalid result", extra={"tool": tool})
        return fail("INTERNAL", "tool produced an invalid result", False, prov_for())
    except Exception:
        log.exception("unexpected error", extra={"tool": tool})
        return fail("INTERNAL", "unexpected error", False, prov_for())


def organ_cores(
    organ: OrganName, cores: Mapping[str, Callable[[Any], Any]]
) -> dict[str, Callable[[Any], Any]]:
    """Check that ``cores`` covers exactly the contract's tools for ``organ``."""
    expected = set(ORGAN_TOOLS[organ])
    got = set(cores)
    if got != expected:
        raise ValueError(
            f"{organ}: cores must match the contract tools; "
            f"missing={sorted(expected - got)} extra={sorted(got - expected)}"
        )
    return dict(cores)
