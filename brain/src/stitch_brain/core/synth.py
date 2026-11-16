"""Synthesis: run every renderer over the evidence store (design 7.1 ``synth`` node)."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from stitch_brain.core.claims import ClaimDraft
from stitch_brain.core.evidence import EvidenceEntry
from stitch_brain.core.templates.allocation import render_allocation
from stitch_brain.core.templates.caveats import render_assumptions, render_caveats_head
from stitch_brain.core.templates.common import RenderCtx
from stitch_brain.core.templates.extent import render_extent
from stitch_brain.core.templates.forecast import render_forecast
from stitch_brain.core.templates.guidance import render_guidance

Renderer = Callable[[RenderCtx], list[ClaimDraft]]
RENDERERS: list[Renderer] = [
    render_extent,
    render_forecast,
    render_guidance,
    render_allocation,
    render_assumptions,
]


def render_all(ctx: RenderCtx, organ_entries: Iterable[EvidenceEntry]) -> list[ClaimDraft]:
    drafts: list[ClaimDraft] = []
    for r in RENDERERS:
        drafts += r(ctx)
    drafts += render_caveats_head(ctx, organ_entries)
    return drafts
