#!/usr/bin/env node
// Dev helper for the visual pass: element-level screenshots after a demo run.
//   node mock-brain/server.mjs --port 4180 --static out   (separately)
//   node scripts/inspect.mjs --lang en --width 1440 --out shots/inspect [--scenario default-demo]
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const arg = (k, d) => {
  const i = process.argv.indexOf(`--${k}`);
  return i >= 0 ? process.argv[i + 1] : d;
};
const origin = arg('origin', 'http://127.0.0.1:4180');
const lang = arg('lang', 'en');
const width = Number(arg('width', 1440));
const out = arg('out', 'shots/inspect');
const scenario = arg('scenario', 'default-demo');
mkdirSync(out, { recursive: true });
await fetch(`${origin}/__mock/config`, { method: 'POST', body: JSON.stringify({ scenario, speed: 8 }) });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width, height: 900 } });
const errors = [];
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
page.on('pageerror', (e) => errors.push(String(e)));
await page.goto(`${origin}/${lang}/`);
await page.waitForTimeout(1500);
await page.keyboard.press('Escape');
await page.getByTestId('run').click();
await page.waitForSelector('[data-testid="confidence"]', { timeout: 30000 });
await page.keyboard.press('Escape');
await page.waitForTimeout(1500);
const tag = `${lang}-${width}`;
const targets = [
  ['header', 'header.site-header'],
  ['control', '#control'],
  ['bench', '#bench'],
  ['map', '#map'],
  ['extent', '#card-extent'],
  ['forecast', '#card-forecast'],
  ['guidance', '#card-guidance'],
  ['allocation', '#card-allocation'],
  ['caveats', '#card-caveats'],
  ['ask', '#ask'],
  ['voice', '[data-testid="voice-controls"]'],
  ['footer', 'footer'],
];
for (const [name, sel] of targets) {
  const el = page.locator(sel).first();
  if (!(await el.count())) {
    console.log(`missing ${sel}`);
    continue;
  }
  await el.screenshot({ path: `${out}/${name}-${tag}.png`, animations: 'disabled' }).catch((e) => console.log(name, String(e).slice(0, 120)));
}
// Horizontal overflow check (reflow at 360 px, WCAG 1.4.10).
const overflow = await page.evaluate(() => {
  const vw = document.documentElement.clientWidth;
  return [...document.querySelectorAll('body *')]
    .filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && (r.right > vw + 1 || r.left < -1) && !e.closest('.table-wrap, .maplibregl-map, .sr-only, [hidden]');
    })
    .slice(0, 12)
    .map((e) => `${e.tagName.toLowerCase()}.${String(e.className).slice(0, 40)} ${Math.round(e.getBoundingClientRect().left)}..${Math.round(e.getBoundingClientRect().right)}`);
});
console.log('overflow:', overflow.length ? overflow.join('\n  ') : 'none');
console.log(errors.length ? errors.join('\n') : 'no console errors');
await browser.close();
