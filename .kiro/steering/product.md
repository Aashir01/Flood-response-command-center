---
inclusion: always
---

# Product: Stitch

Stitch is a flood-response command center. A user picks a region and scenario. Stitch returns a briefing with five parts:

1. Current or predicted flood extent (Eyes).
2. River-level forecast with calibrated uncertainty (Oracle).
3. Grounded guidance with page-level citations (Library).
4. An optimized aid allocation plan with cost-benefit and shadow prices (Ledger).
5. A spoken Urdu or English version of the briefing (Voice).

The Brain orchestrates the organs, detects conflicts between them, self-checks, and attaches provenance to every claim.

## Scenarios

- `demo-sindh-2022` (default): Sindh, August 2022 floods. Fully offline from committed data.
- `live`: region of the user's choice using Open-Meteo forecasts. Requires network. Falls back to demo data with a visible banner when offline.

## Users and tone

Primary persona: a provincial or district disaster officer who needs a 2-minute decision briefing. The UI is spooky (mad-scientist lab) but the content is sober. Never make flood content jokey. Spooky styling applies to chrome and animation, not to the wording of safety guidance.

## Non-negotiables

- Every briefing claim traces to an organ output (provenance). Untraceable claims are removed, not softened.
- Library refuses when evidence is missing. A refusal is a valid, displayed result.
- Uncertainty is always shown (forecast intervals, solver gap, segmentation confidence).
- Demo data is labelled as demo. Never present demo or synthetic output as live.
- Stitch is a decision-support demo. It is not an operational warning system, and the UI says so.

## Priority order (scope rule)

Brain + Library + Ledger end-to-end, then Oracle, then Eyes, then Voice. Every spec's tasks.md marks tasks as `core`, `stretch`, or `cuttable`.

**Voice is time-boxed.** It starts only after the other organs' core tasks are done, has a fixed budget and a go/no-go checkpoint, and is the first cut if the schedule slips.

**Demo-first rule.** Every organ works from the committed demo dataset with no network calls. Live mode is a bonus, never a dependency. Tests for demo paths run with sockets disabled.

## Honest labeling (non-negotiable)
- Oracle output is **modeled** GloFAS discharge (via Open-Meteo). It is never called gauge data or observations, in the UI, evals, or docs.
- Eyes: the Sindh scene is a demo scene. The model is validated on the Sen1Floods11 test split only. The UI labels these separately.
- Voice TTS is a hosted API by default. Any non-commercial local model is optional, off by default, and listed in THIRD_PARTY.md.

## Hackathon constraints

- Built during the submission period. Commit steadily with meaningful messages.
- MIT license. Public repo. `.kiro/` committed and never in `.gitignore`.
- `docker compose up` runs everything with the demo dataset.
- Third-party code, datasets, and models are disclosed in THIRD_PARTY.md.
