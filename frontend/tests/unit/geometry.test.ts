import { describe, expect, it } from 'vitest';
import { bandPath, invert, linear, niceTicks } from '@/lib/scale';
import { circleRadius, labelVisible, ringArea } from '@/lib/geo';

describe('scale', () => {
  it('round trips', () => {
    const s = linear([0, 10], [100, 300]);
    expect(s(5)).toBe(200);
    expect(invert(s, 200)).toBe(5);
  });
  it('nice ticks cover the range', () => {
    const t = niceTicks(0, 97, 5);
    expect(t[0]).toBe(0);
    expect(t.at(-1)).toBeLessThanOrEqual(100);
  });
  it('band path is closed and has 2n+1 vertices', () => {
    const p = bandPath([{ x: 0, p10: 1, p50: 2, p90: 3 }, { x: 10, p10: 2, p50: 3, p90: 4 }], (v) => 100 - v);
    expect(p.endsWith('Z')).toBe(true);
    expect(p.split(' ').length).toBe(5);
  });
});
describe('geo', () => {
  it('labelVisible is pure and thresholded', () => {
    expect(labelVisible(1199)).toBe(false);
    expect(labelVisible(1200)).toBe(true);
  });
  it('ringArea of a square', () => {
    expect(ringArea([[0, 0], [10, 0], [10, 10], [0, 10]])).toBe(100);
  });
  it('circle area is proportional to value', () => {
    expect(circleRadius(100, 100)).toBe(28);
    expect(circleRadius(25, 100)).toBeCloseTo(14);
    expect(circleRadius(0, 100)).toBe(0);
  });
});