export type Ring = [number, number][];

/** Planar shoelace area of a ring in projected pixels. */
export function ringArea(ring: Ring): number {
  let a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i] as [number, number];
    const [xj, yj] = ring[j] as [number, number];
    a += xj * yi - xi * yj;
  }
  return Math.abs(a / 2);
}

export const LABEL_MIN_AREA_PX2 = 1200;

/** Pure declutter rule (design §8.2): hide a district label when its projected area is too small. */
export function labelVisible(projectedAreaPx2: number): boolean {
  return projectedAreaPx2 >= LABEL_MIN_AREA_PX2;
}

/** Allocation circle radius with area proportional to value; largest value gets `maxRadiusPx`. */
export function circleRadius(value: number, maxValue: number, maxRadiusPx = 28): number {
  if (!(maxValue > 0) || !(value > 0)) return 0;
  return maxRadiusPx * Math.sqrt(value / maxValue);
}

export function bboxOf(coords: number[][]): [number, number, number, number] | null {
  if (!coords.length) return null;
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  for (const c of coords) {
    const x = c[0] as number, y = c[1] as number;
    w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y);
  }
  return [w, s, e, n];
}