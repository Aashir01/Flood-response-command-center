// FRN-P5: no animation exceeds the flash-rate limit.
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { bruteForceMaxOnsets, maxOnsetsInWindow } from '@/motion/flashRate';
import { MAX_FLASHES_PER_SECOND, MAX_PEAK_STEP, REGISTRY, SAFE_FLASHES_PER_WINDOW, flashOnsets } from '@/motion/registry';
import { FC_RUNS } from '../helpers/arb';

describe('FRN-P5 flash rate', () => {
  it('every registered flash animation has <= 2 onsets in any 1000 ms window (house rule, stricter than 3 Hz)', () => {
    for (const a of REGISTRY.filter((x) => x.kind === 'flash-overlay' || x.kind === 'fade')) {
      expect(maxOnsetsInWindow(flashOnsets(a)), a.id).toBeLessThanOrEqual(SAFE_FLASHES_PER_WINDOW);
      expect(a.peakStep ?? 0, a.id).toBeLessThanOrEqual(MAX_PEAK_STEP);
    }
  });

  it('every registered animation stays under 3 onsets per second, loops included', () => {
    for (const a of REGISTRY) expect(maxOnsetsInWindow(flashOnsets(a, 20_000)), a.id).toBeLessThanOrEqual(MAX_FLASHES_PER_SECOND);
  });

  it('repeating animations have period >= 800 ms', () => {
    for (const a of REGISTRY) if (a.periodMs !== undefined) expect(a.periodMs, a.id).toBeGreaterThanOrEqual(800);
  });

  it('the awakening finishes within 2.5 s', () => {
    for (const a of REGISTRY.filter((x) => x.id.startsWith('awaken'))) expect(a.durationMs).toBeLessThanOrEqual(2500);
  });

  it('sliding-window count equals brute force', () => {
    fc.assert(
      fc.property(fc.array(fc.integer({ min: 0, max: 5000 }), { maxLength: 30 }), (ts) => {
        expect(maxOnsetsInWindow(ts)).toBe(bruteForceMaxOnsets(ts));
      }),
      { numRuns: FC_RUNS },
    );
  });
});