#!/usr/bin/env node
// Dev helper: screenshots of the built export against a running mock Brain.
//   node mock-brain/server.mjs --port 4173 --static out   (in another terminal)
//   node scripts/shot.mjs [--url http://127.0.0.1:4173/en/] [--out shots] [--width 1440] [--scenario default-demo]
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const arg = (k, d) => {
  const i = process.argv.indexOf(`--${k}`);
  return i >= 0 ? process.argv[i + 1] : d;
};
const url = arg('url', 'http://127.0.0.1:4173/en/');
const out = arg('out', 'shots');
const width = Number(arg('width', 1440));
const scenario = arg('scenario', 'default-demo');
mkdirSync(out, { recursive: true });
const origin = new URL(url).origin;
await fetch(`${origin}/__mock/config`, { method: 'POST', body: JSON.stringify({ scenario, speed: 4 }) });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width, height: 900 } });
const errors = [];
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
page.on('pageerror', (e) => errors.push(String(e)));
await page.goto(url);
await page.waitForTimeout(800);
await page.screenshot({ path: `${out}/boot-${width}.png` });
await page.keyboard.press('Escape');
await page.waitForTimeout(300);
await page.screenshot({ path: `${out}/idle-${width}.png`, fullPage: true });
await page.getByTestId('run').click();
await page.waitForTimeout(900);
await page.screenshot({ path: `${out}/running-${width}.png` });
await page.waitForSelector('[data-testid="confidence"]', { timeout: 30000 });
await page.waitForTimeout(2500);
await page.screenshot({ path: `${out}/done-${width}.png`, fullPage: true });
console.log(errors.length ? errors.join('\n') : 'no console errors');
await browser.close();
