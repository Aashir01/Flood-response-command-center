// WCAG contrast (FRN-R11.2): body AAA, secondary AA, non-text 3:1, in both the default and high-contrast themes.
import { describe, expect, it } from 'vitest';
// @ts-expect-error plain ESM script without types
import { check, contrast, tokens } from '../../scripts/contrast.mjs';

type Row = { fg: string; bg: string; ratio: number; min: number; ok: boolean };

describe('contrast', () => {
  it('formula matches known values', () => {
    expect((contrast as (a: string, b: string) => number)('#ffffff', '#000000')).toBeCloseTo(21, 5);
    expect((contrast as (a: string, b: string) => number)('#eef3f2', '#07090c')).toBeCloseTo(17.79, 1);
  });
  it.each((check as () => Row[])())('$fg on $bg >= $min (default theme)', (r: Row) => {
    expect(r.ratio).toBeGreaterThanOrEqual(r.min);
  });
  it('high-contrast theme keeps every pair passing', () => {
    const hc = { ...(tokens as (b?: string) => Record<string, string>)(), ...(tokens as (b?: string) => Record<string, string>)(":root[data-contrast='more']") };
    for (const r of (check as (s: Record<string, string>) => Row[])(hc)) expect(r.ratio, `${r.fg}/${r.bg}`).toBeGreaterThanOrEqual(r.min);
  });
});
