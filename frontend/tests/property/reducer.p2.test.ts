// FRN-P2: determinism, duplicate/replay idempotence, batching.
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { initialState, reduceAll } from '@/state/benchReducer';
import { FC_RUNS, streamArb } from '../helpers/arb';

describe('FRN-P2 reducer determinism', () => {
  it('(a) same events give deep-equal state', () => {
    fc.assert(fc.property(streamArb, (st) => {
      expect(reduceAll(st)).toEqual(reduceAll(st));
    }), { numRuns: FC_RUNS });
  });

  it('(b) replaying any prefix then the whole stream equals the plain stream', () => {
    fc.assert(
      fc.property(streamArb, fc.nat(40), (st, k) => {
        const cut = Math.min(k, st.length);
        const withReplay = reduceAll([...st.slice(0, cut), ...st]);
        expect(withReplay).toEqual(reduceAll(st));
      }),
      { numRuns: FC_RUNS },
    );
  });

  it('(b2) duplicated frames anywhere are ignored', () => {
    fc.assert(
      fc.property(streamArb, fc.array(fc.nat(40), { maxLength: 10 }), (st, idx) => {
        const dup = st.flatMap((e, i) => (idx.includes(i) ? [e, e] : [e]));
        expect(reduceAll(dup)).toEqual(reduceAll(st));
      }),
      { numRuns: FC_RUNS },
    );
  });

  it('(c) splitting the stream into two batches equals one batch', () => {
    fc.assert(
      fc.property(streamArb, fc.nat(40), (st, k) => {
        const cut = Math.min(k, st.length);
        const two = reduceAll(st.slice(cut), reduceAll(st.slice(0, cut), initialState()));
        expect(two).toEqual(reduceAll(st));
      }),
      { numRuns: FC_RUNS },
    );
  });
});
