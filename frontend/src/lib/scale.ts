export interface LinearScale {
  (v: number): number;
  domain: [number, number];
  range: [number, number];
}

export function linear(domain: [number, number], range: [number, number]): LinearScale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  const f = ((v: number) => r0 + (v - d0) * k) as LinearScale;
  f.domain = domain;
  f.range = range;
  return f;
}

export function invert(s: LinearScale, px: number): number {
  const [d0, d1] = s.domain;
  const [r0, r1] = s.range;
  return r1 === r0 ? d0 : d0 + ((px - r0) * (d1 - d0)) / (r1 - r0);
}

/** "Nice" tick values covering [min, max], at most about `count` ticks. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!(max > min)) return [min];
  const raw = (max - min) / Math.max(1, count);
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / pow;
  const step = (f >= 5 ? 10 : f >= 2 ? 5 : f >= 1 ? 2 : 1) * pow;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(Math.round(v / step) * step);
  return out;
}

/**
 * Nice ticks whose first and last values enclose [min, max] (floor and ceil to the step), so a chart whose
 * y-domain is [first, last] never draws data outside its plot area.
 */
export function niceTicksOuter(min: number, max: number, count = 5): number[] {
  if (!(max > min)) return [min];
  const inner = niceTicks(min, max, count);
  const step = inner.length > 1 ? (inner[1] as number) - (inner[0] as number) : Math.abs(max - min) || 1;
  const lo = Math.floor(min / step + 1e-9) * step;
  const hi = Math.ceil(max / step - 1e-9) * step;
  const out: number[] = [];
  for (let v = lo; v <= hi + step * 1e-9; v += step) out.push(Math.round(v / step) * step);
  return out;
}

export interface BandPoint {
  x: number;
  p10: number;
  p50: number;
  p90: number;
}

/** SVG path for the p10..p90 band: top edge (p90) left to right, bottom edge (p10) right to left. */
export function bandPath(pts: BandPoint[], y: (v: number) => number): string {
  if (!pts.length) return '';
  const top = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(2)},${y(p.p90).toFixed(2)}`);
  const bottom = [...pts].reverse().map((p) => `L${p.x.toFixed(2)},${y(p.p10).toFixed(2)}`);
  return [...top, ...bottom, 'Z'].join(' ');
}

export function linePath(pts: { x: number; y: number }[]): string {
  return pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
}