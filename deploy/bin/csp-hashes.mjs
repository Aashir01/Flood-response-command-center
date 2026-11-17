#!/usr/bin/env node
// Build the gateway's Content-Security-Policy from the Next.js static export (deploy design 5.2).
//   node deploy/bin/csp-hashes.mjs <out-dir>  > csp.caddy
// A static server cannot issue per-request nonces, so every inline <script> body in
// out/**/*.html is hashed (sha256, base64) and the union goes into script-src. If the hash list
// would make the header too large (> MAX_HEADER bytes) the policy falls back to
// 'unsafe-inline' for scripts and says so on stderr (a recorded, known weakness).
// Prints a Caddyfile snippet: `header Content-Security-Policy "<policy>"`.
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const MAX_HEADER = 12000;
const outDir = process.argv[2] ?? 'out';

function* htmlFiles(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* htmlFiles(p);
    else if (name.endsWith('.html')) yield p;
  }
}

const SCRIPT_RE = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
const hashes = new Set();
let files = 0;
for (const file of htmlFiles(outDir)) {
  files += 1;
  const html = readFileSync(file, 'utf8');
  for (const m of html.matchAll(SCRIPT_RE)) {
    const attrs = m[1];
    const body = m[2];
    if (/\bsrc\s*=/.test(attrs)) continue; // external script: covered by 'self'
    if (/type\s*=\s*["']?application\/(ld\+)?json/i.test(attrs)) continue; // data, not executed
    if (body.length === 0) continue;
    hashes.add(`'sha256-${createHash('sha256').update(body, 'utf8').digest('base64')}'`);
  }
}

function policy(scriptSrc) {
  return [
    "default-src 'self'",
    `script-src 'self' ${scriptSrc}`.trim(),
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "media-src 'self' blob:",
    "worker-src 'self' blob:",
    'child-src blob:',
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "manifest-src 'self'",
  ].join('; ');
}

let csp = policy([...hashes].sort().join(' '));
let mode = 'hashes';
if (csp.length > MAX_HEADER) {
  csp = policy("'unsafe-inline'");
  mode = 'unsafe-inline';
}
process.stderr.write(
  `csp-hashes: ${files} html files, ${hashes.size} inline script hashes, mode=${mode}, ` +
    `header ${csp.length} bytes\n`,
);
process.stdout.write(`header Content-Security-Policy "${csp}"\n`);
