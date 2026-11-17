#!/usr/bin/env node
// First-load JS budget (FRN-R12.1): gzip every <script src> that out/<lang>/index.html references and fail
// above 300 KB. Lazy chunks (map, charts, recorder, evidence drawer) are not referenced there, so they are
// excluded by construction. Prints the top contributors. `--json` writes docs-friendly output.
import { readFileSync, existsSync, writeFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(root, 'out');
const BUDGET = 300 * 1024;
const pages = ['en/index.html', 'ur/index.html', 'en/evals/index.html'];
let failed = false;
const report = {};

for (const page of pages) {
  const file = join(out, page);
  if (!existsSync(file)) {
    console.error(`missing ${page}; run next build first`);
    process.exit(1);
  }
  const html = readFileSync(file, 'utf8');
  const srcs = [...new Set([...html.matchAll(/<script[^>]+src="([^"]+\.js)"/g)].map((m) => m[1]))];
  const rows = srcs.map((s) => {
    const p = join(out, s.replace(/^\//, ''));
    const buf = readFileSync(p);
    return { src: s, raw: buf.length, gz: gzipSync(buf, { level: 9 }).length };
  });
  const total = rows.reduce((a, r) => a + r.gz, 0);
  report[page] = { totalGzipBytes: total, files: rows.length };
  console.log(`${page}: ${(total / 1024).toFixed(1)} KB gzip first-load JS in ${rows.length} files (budget ${BUDGET / 1024} KB)`);
  for (const r of rows.sort((a, b) => b.gz - a.gz).slice(0, 5)) console.log(`  ${(r.gz / 1024).toFixed(1).padStart(7)} KB  ${r.src}`);
  if (total > BUDGET) failed = true;
}
if (process.argv.includes('--json')) writeFileSync(join(root, 'budget.json'), JSON.stringify(report, null, 2));
if (failed) {
  console.error('first-load JS budget exceeded');
  process.exit(1);
}
