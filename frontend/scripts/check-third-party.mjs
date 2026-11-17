#!/usr/bin/env node
// Task 21 check: every npm dependency in package.json and every self-hosted font has a THIRD_PARTY.md row.
// Exits 1 and lists what is missing. `npm run check:third-party`.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const front = resolve(here, '..');
const md = readFileSync(resolve(front, '..', 'THIRD_PARTY.md'), 'utf8');
const pkg = JSON.parse(readFileSync(join(front, 'package.json'), 'utf8'));

/** How a package is named in THIRD_PARTY.md when the row uses a display name. */
const ALIAS = {
  next: 'Next.js',
  react: 'React',
  'react-dom': 'React DOM',
  motion: '`motion`',
  'maplibre-gl': 'MapLibre GL JS',
  tailwindcss: 'Tailwind CSS',
  postcss: 'PostCSS',
  typescript: 'TypeScript',
  eslint: 'ESLint',
  vitest: 'Vitest',
  jsdom: 'jsdom',
  '@testing-library/jest-dom': 'jest-dom',
  '@testing-library/react': '@testing-library/react',
  '@testing-library/user-event': 'user-event',
  'fast-check': 'fast-check',
  ajv: 'Ajv',
  'ajv-formats': 'ajv-formats',
};

const missing = [];
for (const [section, deps] of [
  ['dependencies', pkg.dependencies ?? {}],
  ['devDependencies', pkg.devDependencies ?? {}],
]) {
  for (const name of Object.keys(deps)) {
    const needle = ALIAS[name] ?? name;
    if (!md.includes(needle)) missing.push(`${section}: ${name} (looked for "${needle}")`);
  }
}

const FONT_FAMILY = { cinzel: 'Cinzel', 'noto-sans': 'Noto Sans', 'noto-nastaliq-urdu': 'Noto Nastaliq Urdu', 'noto-naskh-arabic': 'Noto Naskh Arabic' };
for (const f of readdirSync(join(front, 'public', 'fonts')).filter((x) => x.endsWith('.woff2'))) {
  const key = Object.keys(FONT_FAMILY).find((k) => f.startsWith(`${k}-`));
  const fam = key ? FONT_FAMILY[key] : null;
  if (!fam || !md.includes(fam)) missing.push(`font: ${f}`);
}

if (missing.length) {
  console.error(`THIRD_PARTY.md is missing ${missing.length} entr${missing.length === 1 ? 'y' : 'ies'}:\n  ${missing.join('\n  ')}`);
  process.exit(1);
}
console.log(`THIRD_PARTY.md lists all ${Object.keys(pkg.dependencies ?? {}).length + Object.keys(pkg.devDependencies ?? {}).length} npm packages and every self-hosted font.`);
