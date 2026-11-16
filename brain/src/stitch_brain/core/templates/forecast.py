"""River forecast claims from the Oracle (design 5.3, 5.4).

The modeled label comes from the evidence: if the Oracle ever returned a ``target_kind`` other
than ``modeled_glofas``, nothing is rendered (the claims would be dropped by the critic anyway).
"""

from __future__ import annotations

from stitch_brain.core.claims import ClaimDraft, SectionId, Slot
from stitch_brain.core.templates.common import RenderCtx, claim, leaf

SEC: SectionId = "forecast"


def render_forecast(ctx: RenderCtx) -> list[ClaimDraft]:
    fc = ctx.ok("oracle.forecast")
    if fc is None:
        return []
    data = fc.data()
    if data.get("target_kind") != "modeled_glofas":
        ctx.issues.append("forecast: target_kind is not modeled_glofas; nothing rendered")
        return []
    out: list[ClaimDraft] = []
    pts = data.get("forecast") or []
    if pts:
        i = max(range(len(pts)), key=lambda k: (float(pts[k]["discharge"]["p50"]), -k))
        base: list[str | int] = ["data", "forecast", i]
        station = (
            leaf("station", fc, ["data", "station", "name"], "text")
            if isinstance(data.get("station"), dict)
            else leaf("station", fc, ["data", "station_id"], "text")
        )
        slots: dict[str, Slot] = {
            "station": station,
            "p50": leaf("p50", fc, [*base, "discharge", "p50"], "int", unit="m3/s"),
            "p10": leaf("p10", fc, [*base, "discharge", "p10"], "int", unit="m3/s"),
            "p90": leaf("p90", fc, [*base, "discharge", "p90"], "int", unit="m3/s"),
            "date": leaf("date", fc, [*base, "date"], "date"),
        }
        out.append(
            claim(
                ctx,
                cid="forecast.peak",
                section=SEC,
                kind="number",
                template_id="forecast.peak",
                slots=slots,
                order=0,
                extra_refs=[fc.ref("/data/target_kind")],
            )
        )
    probs = data.get("exceedance_prob") or []
    if data.get("danger_threshold_m3s") is not None and probs:
        j = max(range(len(probs)), key=lambda k: (float(probs[k]["p_exceed"]), -k))
        slots = {
            "thr": leaf("thr", fc, ["data", "danger_threshold_m3s"], "int", unit="m3/s"),
            "pct": leaf("pct", fc, ["data", "exceedance_prob", j, "p_exceed"], "pct", decimals=0),
            "date": leaf("date", fc, ["data", "exceedance_prob", j, "date"], "date"),
        }
        out.append(
            claim(
                ctx,
                cid="forecast.exceedance",
                section=SEC,
                kind="number",
                template_id="forecast.exceedance",
                slots=slots,
                order=1,
            )
        )
    cal = ["data", "calibration"]
    out.append(
        claim(
            ctx,
            cid="forecast.calibration",
            section=SEC,
            kind="statement",
            template_id="forecast.calibration",
            slots={
                "cov": leaf("cov", fc, [*cal, "nominal_coverage"], "pct", decimals=0),
                "n": leaf("n", fc, [*cal, "n_calibration"], "int"),
            },
            order=2,
            extra_refs=[fc.ref("/data/calibration/method")],
        )
    )
    ex = ctx.ok("oracle.explain")
    if ex is not None and str(ex.data().get("narrative") or "").strip():
        slots = {"narrative": leaf("narrative", ex, ["data", "narrative"], "text")}
        out.append(
            claim(
                ctx,
                cid="forecast.drivers",
                section=SEC,
                kind="statement",
                template_id="forecast.drivers",
                slots=slots,
                order=3,
                extra_refs=[fc.ref("/data/target_kind")],
            )
        )
    return out
