// Lightning awakening timelines (design section 5.5). Flash onsets come from the registry, so the flash-rate
// property test (FRN-P5) covers exactly what the overlay plays.
import { getAnim, MAX_PEAK_STEP } from './registry';
import type { Fx } from './fx';

export type AwakeningKind = 'boot' | 'complete';

export interface Timeline {
  id: string;
  totalMs: number;
  /** Bolt draw-in window, ms; absent when no bolts are drawn. */
  bolts?: { from: number; to: number; fadeAt: number };
  /** Flash envelopes: onset, rise and fall (ms) and peak opacity (fraction of white). */
  flashes: { at: number; rise: number; fall: number; peak: number }[];
  /** Dark veil: fully opaque until `holdUntil`, then fades out by `totalMs`. 0 means no veil. */
  veil: { opacity: number; holdUntil: number };
}

export function timelineFor(kind: AwakeningKind, fx: Fx): Timeline {
  if (fx === 'none' || fx === 'lite') {
    const a = getAnim('awaken-reduced');
    return {
      id: a.id,
      totalMs: a.durationMs,
      flashes: (a.flashAt ?? [0]).map((at) => ({ at, rise: a.durationMs / 2, fall: a.durationMs / 2, peak: a.peakStep ?? 0.12 })),
      veil: { opacity: 0, holdUntil: 0 },
    };
  }
  if (kind === 'boot') {
    const a = getAnim('awaken-boot');
    return {
      id: a.id,
      totalMs: a.durationMs,
      bolts: { from: 0, to: 600, fadeAt: 1300 },
      flashes: (a.flashAt ?? []).map((at) => ({ at, rise: 60, fall: 200, peak: Math.min(MAX_PEAK_STEP, a.peakStep ?? MAX_PEAK_STEP) })),
      veil: { opacity: 1, holdUntil: 1300 },
    };
  }
  const a = getAnim('awaken-complete');
  return {
    id: a.id,
    totalMs: a.durationMs,
    bolts: { from: 0, to: 250, fadeAt: 650 },
    flashes: (a.flashAt ?? []).map((at) => ({ at, rise: 60, fall: 200, peak: Math.min(MAX_PEAK_STEP, a.peakStep ?? MAX_PEAK_STEP) })),
    veil: { opacity: 0.55, holdUntil: 500 },
  };
}

/** WAAPI keyframes for the flash layer over the whole timeline (opacity only). */
export function flashKeyframes(tl: Timeline): Keyframe[] {
  const k: Keyframe[] = [{ opacity: 0, offset: 0 }];
  for (const f of tl.flashes) {
    const o = (ms: number) => Math.min(1, Math.max(0, ms / tl.totalMs));
    if (f.at > 0) k.push({ opacity: 0, offset: o(f.at) });
    k.push({ opacity: f.peak, offset: o(f.at + f.rise) });
    k.push({ opacity: 0, offset: o(f.at + f.rise + f.fall) });
  }
  if ((k.at(-1)?.offset as number) < 1) k.push({ opacity: 0, offset: 1 });
  // Offsets must be non-decreasing.
  let last = 0;
  for (const f of k) {
    f.offset = Math.max(last, f.offset as number);
    last = f.offset as number;
  }
  return k;
}
