---
inclusion: fileMatch
fileMatchPattern: "frontend/**"
---

# UI style: the mad-scientist lab bench

Polished and coherent, not a prototype. Spooky chrome, sober content.

## Metaphor
- **Lab bench**: the main view is a table. Each organ is a jar or limb on it: Eyes (eye in a jar), Oracle (crystal vial), Library (book in a jar), Ledger (brass scales), Voice (a throat or horn).
- **Twitch and glow**: when the Brain calls an organ, its jar twitches and glows. States: `idle`, `calling` (twitch + glow), `done` (steady soft glow), `unwell` (flicker, red-amber, "the organ is unwell"), `disabled`.
- **Lightning awakening**: plays on boot and when a briefing completes. Skippable, under 2.5 s, replaced by a static flash when `prefers-reduced-motion`.
- **Map**: dark "ouija board" style in MapLibre: near-black parchment-toned base, engraved labels, flood extent as luminous green-blue (`--flood-glow`) with a soft outer glow. Permanent water is dimmer, so new flooding stands out.
- **Briefing**: a "vital signs" report: monitor-style cards with pulse lines for river level, a heartbeat strip for confidence, and a chart of forecast bands.

## Tokens (Tailwind theme)
- Backgrounds: `--bg-0 #07090c`, `--bg-1 #0d1217`, `--bg-2 #151c24`.
- Text: `--fg-0 #eef3f2` (body), `--fg-1 #b7c4c2` (secondary). Body contrast at least 7:1 (AAA). Secondary at least 4.5:1.
- Accents: `--flood-glow #2cf5c0`, `--lightning #9fd3ff`, `--ember #ff9d3c`, `--blood #ff4d5e`, `--bone #e8dfc8`.
- Typography: display serif with an engraved feel for headings (e.g. a free "Cinzel"-like face); readable sans for body; Noto Nastaliq Urdu for Urdu display and Noto Naskh Arabic for Urdu body. All fonts self-hosted and listed in THIRD_PARTY.md.
- Radius and spacing from a 4 px scale. Glow is `box-shadow` and `filter: drop-shadow`, never a replacement for borders.

## Required states (every organ and every panel)
Loading (skeleton plus organ twitch), empty, success, partial (some organs unwell), error ("the organ is unwell" with reason, retry, and what the briefing is missing), offline/demo banner.

## Accessibility
- Fully keyboard operable, visible focus ring (2 px `--lightning`), logical tab order, skip link.
- High-contrast: default theme meets AAA for body text; a `high-contrast` toggle raises borders and removes glows.
- All motion respects `prefers-reduced-motion`. No flashing above 3 Hz (seizure safety for the lightning effect).
- Status is never conveyed by color alone (icon plus text).
- Map has a text/table alternative listing districts and flooded area.
- ARIA live region announces organ state changes and briefing completion.

## Sound
Off by default. Toggle in the header, persisted in localStorage. Sounds (thunder, hum) are short, quiet, and CC0 or self-made; listed in THIRD_PARTY.md. Voice briefing playback is separate from ambient sound and always user-initiated.

## Urdu / RTL
- Language toggle: `en` and `ur`. `ur` sets `dir="rtl"` and `lang="ur"` on the document.
- Use logical CSS properties (`margin-inline-start`, etc.). Mirror layout, not charts' time axes or numerals' meaning. Maps keep geographic orientation.
- Numbers: Western digits by default; an option for Eastern Arabic-Indic digits.
- Mixed-direction text uses `<bdi>` for identifiers, units, and citations.

## Responsive
Breakpoints: 360, 768, 1280, 1920. On narrow screens the bench becomes a horizontal organ rail and the briefing stacks under the map.
