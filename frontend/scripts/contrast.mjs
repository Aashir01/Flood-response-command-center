#!/usr/bin/env node
// Recomputes the contrast table (frontend design 11.1) from tokens.css with the WCAG 2.x formula and fails
// if a documented pair drops below its requirement. `node scripts/contrast.mjs` prints the table.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export function luminance(hex) {
  const h = hex.replace('#', '');
  const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
export function contrast(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

export function tokens(block = ':root') {
  const css = readFileSync(resolve(root, 'src/styles/tokens.css'), 'utf8');
  const start = css.indexOf(`${block} {`);
  const body = css.slice(start, css.indexOf('}', start));
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\b/g)].map((m) => [m[1], m[2]]));
}

/** [foreground token, background token, minimum ratio, note] */
export const PAIRS = [
  ['fg-0', 'bg-0', 7, 'body AAA'],
  ['fg-0', 'bg-1', 7, 'body AAA'],
  ['fg-0', 'bg-2', 7, 'body AAA'],
  ['fg-1', 'bg-0', 4.5, 'secondary AA'],
  ['fg-1', 'bg-1', 4.5, 'secondary AA'],
  ['fg-1', 'bg-2', 4.5, 'secondary AA'],
  ['flood-glow', 'bg-2', 7, 'flood text'],
  ['lightning', 'bg-2', 7, 'links and focus'],
  ['ember', 'bg-2', 7, 'warning text'],
  ['bone', 'bg-2', 7, 'labels'],
  ['blood-text', 'bg-2', 7, 'danger text'],
  ['blood', 'bg-2', 3, 'icons and fills only'],
  ['border-ui', 'bg-2', 3, 'control borders (non-text)'],
  ['bg-0', 'flood-glow', 7, 'primary button text'],
];

export function check(set = tokens()) {
  return PAIRS.map(([fg, bg, min, note]) => {
    const r = contrast(set[fg], set[bg]);
    return { fg, bg, ratio: Math.round(r * 100) / 100, min, note, ok: r >= min };
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const rows = [...check(), ...check({ ...tokens(), ...tokens(":root[data-contrast='more']") }).map((r) => ({ ...r, note: `${r.note} (high contrast)` }))];
  for (const r of rows) console.log(`${r.ok ? 'ok  ' : 'FAIL'} ${r.fg.padEnd(11)} on ${r.bg.padEnd(10)} ${String(r.ratio).padStart(6)} >= ${r.min}  ${r.note}`);
  if (rows.some((r) => !r.ok)) process.exit(1);
}
