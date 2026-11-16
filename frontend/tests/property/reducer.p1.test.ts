// FRN-P1: every organ has exactly one visible state, equal to a reference model.
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { benchReducer, initialState, reduceAll, type OrganState } from '@/state/benchReducer';
import { ORGAN_IDS, type OrganId } from '@/api/types';
import { FC_RUNS, healthArb, streamArb, type Spec } from '../helpers/arb';

const STATES: OrganState[] = ['idle', 'calling', 'done', 'unwell', 'disabled'];

function modelState(base: OrganState, o: OrganId, specs: Spec[]): OrganState {
  let st = base;
  for (const sp of specs) {
    if (st === 'disabled') continue;
    if ((sp.k === 'call' || sp.k === 'ok' || sp.k === 'fail' || sp.k === 'organError') && sp.o === o) {
      st = sp.k === 'call' ? 'calling' : sp.k === 'ok' ? 'done' : 'unwell';
    } else if (sp.k === 'briefing' && st === 'calling') st = 'unwell';
    else if (sp.k === 'fatal' && sp.cancelled && st === 'calling') st = base;
  }
  return st;
}

describe('FRN-P1 organ state equals reference model', () => {
  it('every organ has exactly one state from the five-value set and it matches the model', () => {
    fc.assert(
      fc.property(healthArb, streamArb, (health, stream) => {
        let s = benchReducer(initialState(), { type: 'HEALTH', organs: health });
        const base = { ...s.baseline };
        s = reduceAll(stream, s);
        for (const o of ORGAN_IDS) {
          expect(STATES).toContain(s.organs[o].state);
          expect(s.organs[o].state).toBe(modelState(base[o], o, stream.map((e) => e.spec)));
        }
      }),
      { numRuns: FC_RUNS },
    );
  });

  it('disabled organs never leave disabled', () => {
    fc.assert(
      fc.property(streamArb, (stream) => {
        const health = ORGAN_IDS.map((organ) => ({ organ, status: 'disabled' as const }));
        const s = reduceAll(stream, benchReducer(initialState(), { type: 'HEALTH', organs: health }));
        for (const o of ORGAN_IDS) expect(s.organs[o].state).toBe('disabled');
      }),
      { numRuns: FC_RUNS },
    );
  });

  it('STREAM_LOST keeps organ states', () => {
    fc.assert(
      fc.property(streamArb, (stream) => {
        const s = reduceAll(stream);
        const lost = benchReducer(s, { type: 'STREAM_LOST' });
        for (const o of ORGAN_IDS) expect(lost.organs[o].state).toBe(s.organs[o].state);
      }),
      { numRuns: FC_RUNS },
    );
  });
});