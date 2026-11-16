// One-off repair: undoes UTF-8 -> cp1252 -> UTF-8 double encoding (applied repeatedly until stable).
// Usage: node scripts/fix-mojibake.mjs <file>...
import { readFileSync, writeFileSync } from 'node:fs';

const CP1252 = {
  0x20ac: 0x80, 0x201a: 0x82, 0x0192: 0x83, 0x201e: 0x84, 0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87, 0x02c6: 0x88,
  0x2030: 0x89, 0x0160: 0x8a, 0x2039: 0x8b, 0x0152: 0x8c, 0x017d: 0x8e, 0x2018: 0x91, 0x2019: 0x92, 0x201c: 0x93,
  0x201d: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97, 0x02dc: 0x98, 0x2122: 0x99, 0x0161: 0x9a, 0x203a: 0x9b,
  0x0153: 0x9c, 0x017e: 0x9e, 0x0178: 0x9f,
};
const byteOf = (ch) => {
  const c = ch.codePointAt(0);
  if (c >= 0x80 && c <= 0xff) return c;
  return CP1252[c];
};
const dec = new TextDecoder('utf-8', { fatal: true });
const RUN = /[\u0080-\u00ff\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013\u2014\u2018-\u201e\u2020-\u2022\u2026\u2030\u2039\u203a\u20ac\u2122]{2,}/g;

function fixOnce(s) {
  return s.replace(RUN, (run) => {
    const bytes = [...run].map(byteOf);
    if (bytes.some((b) => b === undefined)) return run;
    try {
      return dec.decode(new Uint8Array(bytes));
    } catch {
      return run;
    }
  });
}

for (const f of process.argv.slice(2)) {
  let s = readFileSync(f, 'utf8');
  for (let i = 0; i < 4; i++) {
    const n = fixOnce(s);
    if (n === s) break;
    s = n;
  }
  writeFileSync(f, s);
  console.log(f, (s.match(/[\u0600-\u06ff]/g) || []).length, 'arabic-script chars');
}
