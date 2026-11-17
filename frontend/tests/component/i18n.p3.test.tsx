// FRN-P3: switching language twice returns the same DOM text as before (round trip).
import { cleanup, render } from '@testing-library/react';
import fc from 'fast-check';
import { afterEach, describe, expect, it } from 'vitest';
import type { Lang } from '@/api/types';
import { LabBench } from '@/components/bench/LabBench';
import { ScenarioControl } from '@/components/bench/ScenarioControl';
import { Header } from '@/components/shell/Header';
import { DecisionSupportNotice } from '@/components/shell/Banners';
import { reduceAll } from '@/state/benchReducer';
import { FC_RUNS, specArb, toEvent } from '../helpers/arb';
import { benchValue, Wrap } from '../helpers/render';

afterEach(cleanup);

const norm = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim();

function Chrome({ lang, bench }: { lang: Lang; bench: ReturnType<typeof benchValue> }) {
  return (
    <Wrap lang={lang} bench={bench}>
      <Header route="" mode="demo" />
      <DecisionSupportNotice />
      <ScenarioControl />
      <LabBench />
    </Wrap>
  );
}

describe('FRN-P3 language round trip', () => {
  it('an even number of toggles restores the DOM text, for any bench state', () => {
    fc.assert(
      fc.property(fc.array(specArb, { maxLength: 20 }), fc.integer({ min: 1, max: 3 }), fc.constantFrom<Lang>('en', 'ur'), (specs, pairs, start) => {
        const state = reduceAll(specs.map((s, i) => ({ seq: i + 1, event: toEvent(s, i + 1) })));
        const bench = benchValue(state);
        const { container, rerender, unmount } = render(<Chrome lang={start} bench={bench} />);
        const before = norm(container.textContent);
        let lang = start;
        const other = start === 'en' ? 'ur' : 'en';
        for (let i = 0; i < pairs * 2; i++) {
          lang = lang === 'en' ? 'ur' : 'en';
          rerender(<Chrome lang={lang} bench={bench} />);
          if (i === 0) expect(norm(container.textContent)).not.toEqual(before); // it really switched
        }
        expect(lang).toBe(start);
        expect(norm(container.textContent)).toEqual(before);
        expect(other).not.toBe(start);
        unmount();
      }),
      { numRuns: Math.min(FC_RUNS, 20) },
    );
  }, 120_000);
});
