import { describe, expect, it } from 'vitest';
import en from '@/i18n/messages/en.json';
import ur from '@/i18n/messages/ur.json';
import { makeFmt } from '@/i18n/format';
import { interpolate, placeholders } from '@/i18n/t';

describe('dictionaries (FRN-R8.3)', () => {
  it('Urdu has exactly the English key set', () => {
    expect(Object.keys(ur).sort()).toEqual(Object.keys(en).sort());
  });
  it('every key has the same placeholders in both languages', () => {
    for (const k of Object.keys(en) as (keyof typeof en)[]) expect(placeholders(ur[k]), k).toEqual(placeholders(en[k]));
  });
  it('no message is empty', () => {
    for (const [k, v] of [...Object.entries(en), ...Object.entries(ur)]) expect(v.trim().length, k).toBeGreaterThan(0);
  });
  it('Urdu strings are actually Urdu for prose keys', () => {
    expect(ur['state.unwell']).toMatch(/[\u0600-\u06FF]/);
    expect(ur['sleeps.title']).toMatch(/[\u0600-\u06FF]/);
  });
  it('the Oracle label is never "gauge" or "observed" (FRN-R14.3)', () => {
    for (const d of [en, ur]) for (const v of Object.values(d)) expect(v.toLowerCase()).not.toMatch(/\bgauge|\bobserved/);
  });
  it('interpolate leaves unknown placeholders intact', () => {
    expect(interpolate('{a} and {b}', { a: 1 })).toBe('1 and {b}');
  });
});

describe('number formatting', () => {
  it('Western digits by default, also for Urdu', () => {
    expect(makeFmt('ur').int(12345)).toMatch(/12,?345/);
    expect(makeFmt('en').int(12345)).toBe('12,345');
  });
  it('Urdu digits option uses extended Arabic-Indic digits U+06F0..U+06F9', () => {
    const s = makeFmt('ur', 'arabext').int(1234567890);
    expect(s).toMatch(/[\u06F0-\u06F9]/);
    expect(s).not.toMatch(/[0-9]/);
  });
  it('missing values render as an en dash', () => {
    expect(makeFmt('en').num(null)).toBe('–');
    expect(makeFmt('en').pct(undefined)).toBe('–');
  });
});
