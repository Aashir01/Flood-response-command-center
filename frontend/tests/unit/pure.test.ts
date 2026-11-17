import { describe, expect, it } from 'vitest';
import { evalsState, metricPasses } from '@/components/evals/EvalHeartbeat';
import { allocationFeatures, buildRows, MAX_RADIUS_PX } from '@/components/map/mapData';
import { forecastDomain } from '@/components/charts/ForecastBandChart';
import { flashKeyframes, timelineFor } from '@/motion/awakening';
import { maxOnsetsInWindow } from '@/motion/flashRate';
import { MAX_PEAK_STEP, SAFE_FLASHES_PER_WINDOW } from '@/motion/registry';
import { MASTER_GAIN, RECIPES, recipeLength } from '@/sound/voices';
import { downsample, encodeWav } from '@/voice/wav';
import type { CompareOut, ForecastOut, OptimizeOut, ScenarioDistrict } from '@/api/types';
import { evals, toolData } from '../helpers/fixtures';

describe('awakening timelines (FRN-R1, FRN-P5)', () => {
  for (const kind of ['boot', 'complete'] as const)
    for (const fx of ['full', 'lite', 'none'] as const) {
      it(`${kind}/${fx}: <= 2.5 s, <= 2 flashes per second, peak <= 0.3`, () => {
        const tl = timelineFor(kind, fx);
        expect(tl.totalMs).toBeLessThanOrEqual(2500);
        expect(maxOnsetsInWindow(tl.flashes.map((f) => f.at))).toBeLessThanOrEqual(SAFE_FLASHES_PER_WINDOW);
        for (const f of tl.flashes) expect(f.peak).toBeLessThanOrEqual(MAX_PEAK_STEP);
        const k = flashKeyframes(tl);
        const offs = k.map((x) => x.offset as number);
        expect([...offs].sort((a, b) => a - b)).toEqual(offs);
        for (const x of k) expect(x.opacity as number).toBeLessThanOrEqual(MAX_PEAK_STEP);
      });
    }
  it('reduced motion has no bolts and exactly one flash', () => {
    const tl = timelineFor('boot', 'none');
    expect(tl.bolts).toBeUndefined();
    expect(tl.flashes).toHaveLength(1);
  });
  it('completion is shorter than boot', () => {
    expect(timelineFor('complete', 'full').totalMs).toBeLessThan(timelineFor('boot', 'full').totalMs);
  });
});

describe('sound recipes (FRN-R7)', () => {
  it('are pure, quiet descriptions under the master cap', () => {
    expect(MASTER_GAIN).toBeLessThanOrEqual(0.3);
    for (const r of Object.values(RECIPES)) {
      expect(r.env.peak).toBeLessThanOrEqual(0.35);
      if (!r.env.sustain) expect(recipeLength(r)).toBeLessThanOrEqual(2);
      expect(JSON.parse(JSON.stringify(r))).toEqual(r);
    }
    expect(Object.keys(RECIPES).sort()).toEqual(['done', 'hum', 'thunder', 'twitch', 'unwell']);
  });
});

describe('WAV encoder (FRN-R6)', () => {
  it('writes a valid 16 kHz mono 16-bit little-endian header and samples', () => {
    const s = new Float32Array([0, 0.5, -0.5, 1, -1, 2]);
    const buf = encodeWav(s, 16000);
    const v = new DataView(buf);
    const str = (o: number, n: number) => String.fromCharCode(...new Uint8Array(buf, o, n));
    expect(str(0, 4)).toBe('RIFF');
    expect(str(8, 4)).toBe('WAVE');
    expect(str(36, 4)).toBe('data');
    expect(v.getUint32(4, true)).toBe(36 + s.length * 2);
    expect(v.getUint16(20, true)).toBe(1);
    expect(v.getUint16(22, true)).toBe(1);
    expect(v.getUint32(24, true)).toBe(16000);
    expect(v.getUint16(34, true)).toBe(16);
    expect(v.getUint32(40, true)).toBe(s.length * 2);
    expect(buf.byteLength).toBe(44 + s.length * 2);
    expect(v.getInt16(44 + 2, true)).toBe(Math.round(0.5 * 0x7fff));
    expect(v.getInt16(44 + 8, true)).toBe(-0x8000);
    expect(v.getInt16(44 + 10, true)).toBe(0x7fff); // clipped
  });
  it('downsamples 48 kHz to 16 kHz by a factor of three', () => {
    expect(downsample(new Float32Array(4800), 48000).length).toBe(1600);
  });
});

describe('map rows (FRN-R4.5)', () => {
  const compare = toolData<CompareOut>('default-demo', 'compare_with_permanent_water');
  const opt = toolData<OptimizeOut>('default-demo', 'optimize_allocation');
  const districts = (toolData<{ items: ScenarioDistrict[] }>('default-demo', 'resource:districts')).items;
  const rows = buildRows([], new Map(districts.map((d, i) => [d.district_id, [68 + i * 0.1, 26] as [number, number]])), compare, opt, districts);
  it('one row per district, with the same numbers the organs reported', () => {
    expect(rows).toHaveLength(22);
    const dadu = rows.find((r) => r.id === 'pk-sindh-dadu');
    expect(dadu?.floodedKm2).toBe(compare.by_district.find((d) => d.district_id === 'pk-sindh-dadu')?.flooded_km2);
    expect(dadu?.allocation.water).toBe(opt.allocation.find((a) => a.district_id === 'pk-sindh-dadu' && a.commodity_id === 'water')?.quantity);
  });
  it('allocation circle area is proportional to people covered; largest is the max radius', () => {
    const fc = allocationFeatures(rows);
    const maxP = Math.max(...fc.features.map((f) => f.properties.people_covered));
    for (const f of fc.features) {
      const r = f.properties.k * Math.sqrt(f.properties.people_covered);
      expect(r).toBeLessThanOrEqual(MAX_RADIUS_PX + 1e-9);
      expect((r * r) / (MAX_RADIUS_PX * MAX_RADIUS_PX)).toBeCloseTo(f.properties.people_covered / maxP, 9);
    }
  });
});

describe('forecast domain', () => {
  it('contains every interval and the threshold', () => {
    const f = toolData<ForecastOut>('default-demo', 'forecast_river');
    const [lo, hi] = forecastDomain(f);
    for (const p of f.forecast) {
      expect(p.discharge.p10).toBeGreaterThanOrEqual(lo);
      expect(p.discharge.p90).toBeLessThanOrEqual(hi);
    }
    expect(f.danger_threshold_m3s as number).toBeLessThanOrEqual(hi);
  });
});

describe('eval states (FRN-R9.2)', () => {
  const now = Date.parse('2026-11-21T00:00:00Z');
  it('classifies the four fixtures', () => {
    expect(evalsState(evals('empty'), now)).toBe('none');
    expect(evalsState(evals('full'), now)).toBe('full');
    expect(evalsState(evals('partial'), now)).toBe('partial');
    expect(evalsState(evals('stale'), Date.parse('2026-12-31T00:00:00Z'))).toBe('stale');
    expect(evalsState(evals('full'), now, 'othersha')).toBe('stale');
    expect(evalsState(null, now)).toBe('none');
  });
  it('pass/fail follows the direction', () => {
    const base = { id: 'x', label: 'x', dataset: 'd', timestamp: '', git_sha: '', seed: 1 };
    expect(metricPasses({ ...base, value: 1, target: 2, direction: 'lower' })).toBe(true);
    expect(metricPasses({ ...base, value: 1, target: 2, direction: 'higher' })).toBe(false);
    expect(metricPasses({ ...base, value: 1, target: null, direction: 'higher' })).toBeNull();
  });
});
