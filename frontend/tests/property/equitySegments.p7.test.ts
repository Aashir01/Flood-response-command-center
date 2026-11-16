// FRN-P7: the equity chart never interpolates across infeasible points.
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { buildSegments, type EquityPoint } from '@/lib/equitySegments';
import { FC_RUNS } from '../helpers/arb';

const pointsArb = fc
  .uniqueArray(fc.integer({ min: 0, max: 100 }), { minLength: 1, maxLength: 21 })
  .chain((floors) =>
    fc.tuple(...floors.map(() => fc.constantFrom<EquityPoint['status']>('optimal', 'feasible', 'infeasible'))).map((sts) =>
      floors.map<EquityPoint>((f, i) => {
        const infeasible = sts[i] === 'infeasible';
        return { min_coverage_floor: f / 100, status: sts[i] as EquityPoint['status'], total_coverage: infeasible ? null : 1000 - f * 3, people_covered: infeasible ? null : 5000 - f * 10 };
      }),
    ),
  );

describe('FRN-P7 equity segments', () => {
  it('segments contain only feasible points and never span an infeasible index', () => {
    fc.assert(
      fc.property(pointsArb, (pts) => {
        const { sorted, segments, infeasible } = buildSegments(pts);
        for (const seg of segments) {
          for (const p of seg) expect(p.status).not.toBe('infeasible');
          const idx = seg.map((p) => sorted.indexOf(p));
          for (let i = 1; i < idx.length; i++) expect(idx[i]).toBe((idx[i - 1] as number) + 1);
        }
        const infeasibleIdx = sorted.map((p, i) => (p.status === 'infeasible' ? i : -1)).filter((i) => i >= 0);
        const covered = infeasible.flatMap((r) => Array.from({ length: r.toIndex - r.fromIndex + 1 }, (_, k) => r.fromIndex + k));
        expect(covered).toEqual(infeasibleIdx);
        const feasibleCount = sorted.filter((p) => p.status !== 'infeasible').length;
        expect(segments.reduce((n, s) => n + s.length, 0)).toBe(feasibleCount);
      }),
      { numRuns: FC_RUNS },
    );
  });

  it('slider snap values equal the input floors (no interpolated values)', () => {
    fc.assert(
      fc.property(pointsArb, (pts) => {
        const { sorted } = buildSegments(pts);
        expect(sorted.map((p) => p.min_coverage_floor)).toEqual([...pts.map((p) => p.min_coverage_floor)].sort((a, b) => a - b));
      }),
      { numRuns: FC_RUNS },
    );
  });
});