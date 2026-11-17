// FRN-P6: every rendered Oracle-derived value has an adjacent "Modeled (GloFAS)" label, and Oracle output is
// never called "gauge" or "observed".
import { cleanup, render } from '@testing-library/react';
import fc from 'fast-check';
import { afterEach, describe, expect, it } from 'vitest';
import type { Claim, ForecastOut } from '@/api/types';
import { ClaimItem } from '@/components/briefing/ClaimItem';
import { OracleValue } from '@/components/briefing/labels';
import { ForecastBandChart } from '@/components/charts/ForecastBandChart';
import { EvalBody } from '@/components/evals/EvalHeartbeat';
import en from '@/i18n/messages/en.json';
import ur from '@/i18n/messages/ur.json';
import { FC_RUNS } from '../helpers/arb';
import { evals, toolData } from '../helpers/fixtures';
import { Wrap } from '../helpers/render';

afterEach(cleanup);

function assertLabelled(root: HTMLElement, lang: 'en' | 'ur') {
  const label = lang === 'en' ? en['label.modeled'] : ur['label.modeled'];
  const values = root.querySelectorAll('[data-oracle-value]');
  expect(values.length).toBeGreaterThan(0);
  values.forEach((v) => {
    const l = v.querySelector('[data-modeled-label]') ?? (v.matches('[data-modeled-label]') ? v : null);
    expect(l, v.outerHTML.slice(0, 120)).not.toBeNull();
    expect(l?.textContent).toContain(label);
  });
  expect(root.textContent?.toLowerCase()).not.toMatch(/\bgauge|\bobserved/);
}

const forecastArb = fc
  .array(
    fc.tuple(fc.integer({ min: 100, max: 30000 }), fc.integer({ min: 0, max: 3000 }), fc.integer({ min: 0, max: 3000 }), fc.double({ min: 0, max: 1, noNaN: true })),
    { minLength: 1, maxLength: 14 },
  )
  .chain((rows) =>
    fc.option(fc.integer({ min: 100, max: 30000 }), { nil: null }).map(
      (thr) =>
        ({
          station_id: 'indus-sukkur',
          unit: 'm3/s',
          as_of: '2022-08-30',
          target_kind: 'modeled_glofas',
          target_label: 'Modeled river discharge (GloFAS via Open-Meteo)',
          forecast: rows.map(([p50, lo, hi], i) => ({ date: `2022-09-${String(i + 1).padStart(2, '0')}`, lead_days: i + 1, discharge: { p10: p50 - lo, p50, p90: p50 + hi } })),
          danger_threshold_m3s: thr,
          exceedance_prob: rows.map(([, , , pe], i) => ({ date: `2022-09-${String(i + 1).padStart(2, '0')}`, p_exceed: pe })),
          calibration: { method: 'split_conformal', nominal_coverage: 0.8, n_calibration: 180 },
        }) as ForecastOut,
    ),
  );

describe('FRN-P6 Modeled (GloFAS) label', () => {
  it.each(['en', 'ur'] as const)('forecast chart with generated data (%s)', (lang) => {
    fc.assert(
      fc.property(forecastArb, (f) => {
        const { container, unmount } = render(
          <Wrap lang={lang}>
            <ForecastBandChart forecast={f} />
          </Wrap>,
        );
        assertLabelled(container, lang);
        // The chart's accessible name carries the label too.
        expect(container.querySelector('svg[role="img"]')?.getAttribute('aria-label')).toContain(lang === 'en' ? en['label.modeled'] : ur['label.modeled']);
        unmount();
      }),
      { numRuns: Math.min(FC_RUNS, 25) },
    );
  });

  it('the fixture forecast renders with the label', () => {
    const { container } = render(
      <Wrap>
        <ForecastBandChart forecast={toolData<ForecastOut>('default-demo', 'forecast_river')} />
      </Wrap>,
    );
    assertLabelled(container, 'en');
  });

  it('OracleValue always carries the label', () => {
    fc.assert(
      fc.property(fc.double({ noNaN: true }), (n) => {
        const { container, unmount } = render(
          <Wrap>
            <OracleValue unit="m³/s">{String(n)}</OracleValue>
          </Wrap>,
        );
        assertLabelled(container, 'en');
        unmount();
      }),
      { numRuns: Math.min(FC_RUNS, 30) },
    );
  });

  it('a claim evidenced by the Oracle shows the label', () => {
    const c = { id: 'f', kind: 'number', text: 'Peak 18,100 m3/s', evidence: [{ run_id: 'r', organ: 'oracle', tool: 'forecast_river', json_pointer: '/data/forecast/0/discharge/p50' }] } as Claim;
    const { container } = render(
      <Wrap>
        <ul>
          <ClaimItem claim={c} lang="en" />
        </ul>
      </Wrap>,
    );
    assertLabelled(container, 'en');
  });

  it('eval rows for the Oracle carry the label', () => {
    const { container } = render(
      <Wrap>
        <EvalBody data={evals('full')} now={Date.parse('2026-11-21T00:00:00Z')} />
      </Wrap>,
    );
    assertLabelled(container, 'en');
    expect(container.querySelectorAll('[data-organ="oracle"] [data-modeled-label]').length).toBeGreaterThan(0);
  });
});
