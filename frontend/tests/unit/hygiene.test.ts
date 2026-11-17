// Static hygiene: logical CSS only, no text-size use of --blood, no external URLs in the map style or app code.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const root = resolve(__dirname, '..', '..');
function walk(dir: string, ext: RegExp, out: string[] = []): string[] {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) {
      if (f === 'gen') continue;
      walk(p, ext, out);
    } else if (ext.test(f)) out.push(p);
  }
  return out;
}
const src = walk(join(root, 'src'), /\.(tsx?|css)$/);

describe('hygiene', () => {
  it('no physical Tailwind utilities (ml-, mr-, pl-, pr-, left-, right-, text-left, text-right, rounded-l/r)', () => {
    const bad = /\b(?:m[lr]|p[lr]|left|right|rounded-[lr]|text-(?:left|right))-[\w[]/;
    for (const f of src.filter((x) => x.endsWith('.tsx'))) {
      for (const m of readFileSync(f, 'utf8').matchAll(/className="([^"]+)"/g)) expect(bad.test(m[1] as string), `${f}: ${m[1]}`).toBe(false);
    }
  });
  it('no physical CSS properties in our stylesheets (logical properties only)', () => {
    const css = src.filter((x) => x.endsWith('.css'));
    const bad = /(?:^|[\s;{])(?:margin|padding|border)-(?:left|right)\s*:|(?:^|[\s;{])(?:left|right)\s*:|text-align:\s*(?:left|right)/m;
    for (const f of css) expect(bad.test(readFileSync(f, 'utf8')), f).toBe(false);
  });
  it('--blood is never used as a text colour (5.29:1 is below AAA)', () => {
    for (const f of src) {
      const s = readFileSync(f, 'utf8');
      for (const m of s.matchAll(/([^{}]+)\{([^}]*)\}/g))
        if (/(?:^|[^-])color:\s*var\(--blood\)/.test(m[2] as string)) expect(/svg|icon/.test(m[1] as string), `${f}: ${m[1]}`).toBe(true);
      expect(/\btext-blood\b(?!-text)/.test(s), f).toBe(false);
    }
  });
  it('map style has no external URLs, glyphs or sprite', () => {
    const style = readFileSync(join(root, 'public/map/style.json'), 'utf8');
    expect(style).not.toMatch(/https?:\/\//);
    const j = JSON.parse(style) as Record<string, unknown>;
    expect(j.glyphs).toBeUndefined();
    expect(j.sprite).toBeUndefined();
  });
  it('app code calls no external origin (demo-first)', () => {
    for (const f of src) {
      const s = readFileSync(f, 'utf8');
      for (const m of s.matchAll(/fetch\(\s*['"`]([^'"`]+)/g)) expect(m[1]?.startsWith('/') || m[1]?.startsWith('${BRAIN_URL}'), `${f}: ${m[1]}`).toBe(true);
      expect(/https?:\/\/(?!www\.w3\.org)/.test(s.replace(/\/\/.*$/gm, '')), f).toBe(false);
    }
  });
  it('raw motion components are not used (only the lazy `m`)', () => {
    for (const f of src) expect(/\bmotion\.(div|g|span|svg|path)\b/.test(readFileSync(f, 'utf8')), f).toBe(false);
  });
});
