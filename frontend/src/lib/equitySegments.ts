export interface EquityPoint {
  min_coverage_floor: number;
  status: 'optimal' | 'feasible' | 'infeasible';
  total_coverage: number | null;
  people_covered: number | null;
}
export interface InfeasibleRange {
  fromIndex: number;
  toIndex: number;
  fromFloor: number;
  toFloor: number;
}
export interface Segments {
  /** The points sorted by floor (the slider's snap positions). */
  sorted: EquityPoint[];
  /** Maximal runs of consecutive feasible points. A polyline is drawn per run only. */
  segments: EquityPoint[][];
  /** Maximal runs of consecutive infeasible points (indices into `sorted`). */
  infeasible: InfeasibleRange[];
}

const feasible = (p: EquityPoint) => p.status !== 'infeasible' && p.total_coverage !== null;

/** FRN-P7: never draws a line across or into an infeasible point, never interpolates. */
export function buildSegments(points: readonly EquityPoint[]): Segments {
  const sorted = [...points].sort((a, b) => a.min_coverage_floor - b.min_coverage_floor);
  const segments: EquityPoint[][] = [];
  const infeasible: InfeasibleRange[] = [];
  let cur: EquityPoint[] = [];
  let bad: { from: number; to: number } | null = null;
  sorted.forEach((p, i) => {
    if (feasible(p)) {
      cur.push(p);
      if (bad) {
        infeasible.push({ fromIndex: bad.from, toIndex: bad.to, fromFloor: (sorted[bad.from] as EquityPoint).min_coverage_floor, toFloor: (sorted[bad.to] as EquityPoint).min_coverage_floor });
        bad = null;
      }
    } else {
      if (cur.length) segments.push(cur);
      cur = [];
      bad = bad ? { from: bad.from, to: i } : { from: i, to: i };
    }
  });
  if (cur.length) segments.push(cur);
  if (bad) {
    const b: { from: number; to: number } = bad;
    infeasible.push({ fromIndex: b.from, toIndex: b.to, fromFloor: (sorted[b.from] as EquityPoint).min_coverage_floor, toFloor: (sorted[b.to] as EquityPoint).min_coverage_floor });
  }
  return { sorted, segments, infeasible };
}