// Every animation in the app is declared here so FRN-P5 (<= 3 flashes/s) can inspect them without rendering.
// A "flash" is a luminance step of the overlay or glow; `flashAt` lists onset timestamps in ms from start.
export type AnimKind = 'flash-overlay' | 'twitch' | 'glow-loop' | 'pulse' | 'fade' | 'stagger';
export interface AnimSpec {
  id: string;
  kind: AnimKind;
  durationMs: number;
  /** Repeat period for loops (ms). Absent means one-shot. */
  periodMs?: number;
  /** Flash onsets for one-shot flash animations, ms from start. */
  flashAt?: number[];
  /** Peak luminance step as a fraction of full white. */
  peakStep?: number;
}

export const MAX_FLASHES_PER_SECOND = 3;
export const SAFE_FLASHES_PER_WINDOW = 2; // stricter house rule, design §5.5
export const MAX_PEAK_STEP = 0.3;

export const DURATIONS = { instant: 80, quick: 160, base: 240, slow: 400, awaken: 2300 } as const;

export const REGISTRY: AnimSpec[] = [
  { id: 'awaken-boot', kind: 'flash-overlay', durationMs: 2300, flashAt: [700, 1200], peakStep: 0.3 },
  { id: 'awaken-complete', kind: 'flash-overlay', durationMs: 1200, flashAt: [300], peakStep: 0.3 },
  { id: 'awaken-reduced', kind: 'fade', durationMs: 200, flashAt: [0], peakStep: 0.12 },
  { id: 'jar-calling-twitch', kind: 'twitch', durationMs: 420, periodMs: 1300 },
  { id: 'jar-calling-glow', kind: 'glow-loop', durationMs: 1300, periodMs: 1300 },
  { id: 'jar-unwell-flicker', kind: 'glow-loop', durationMs: 900, periodMs: 900 },
  { id: 'jar-done-glow', kind: 'fade', durationMs: 400 },
  { id: 'pulse-line', kind: 'pulse', durationMs: 2400, periodMs: 2400 },
  { id: 'heartbeat-strip', kind: 'pulse', durationMs: 1200, periodMs: 1200 },
  { id: 'card-enter', kind: 'stagger', durationMs: 240 },
];

export function getAnim(id: string): AnimSpec {
  const a = REGISTRY.find((x) => x.id === id);
  if (!a) throw new Error(`unknown animation ${id}`);
  return a;
}

/** Onsets of every flash an animation produces over `horizonMs`, expanding loops. */
export function flashOnsets(a: AnimSpec, horizonMs = 10_000): number[] {
  const base = a.flashAt ?? (a.kind === 'glow-loop' || a.kind === 'twitch' || a.kind === 'pulse' ? [0] : []);
  if (!a.periodMs) return base.slice();
  const out: number[] = [];
  for (let t = 0; t < horizonMs; t += a.periodMs) for (const f of base) out.push(t + f);
  return out;
}