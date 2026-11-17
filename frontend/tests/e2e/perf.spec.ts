// Performance smoke (FRN-R12): LCP of /en/ and /ur/ from the browser's own largest-contentful-paint entries,
// with 4x CPU throttling, plus the frame-time sample during a run. Numbers are written to test-results/perf.json
// and copied into docs/frontend-performance.md by hand.
import { expect, test } from '@playwright/test';
import { mkdirSync, writeFileSync, existsSync, readFileSync } from 'node:fs';
import { mock } from './helpers';

const OUT = 'test-results/perf.json';
function record(key: string, value: unknown) {
  mkdirSync('test-results', { recursive: true });
  const cur = existsSync(OUT) ? (JSON.parse(readFileSync(OUT, 'utf8')) as Record<string, unknown>) : {};
  cur[key] = value;
  writeFileSync(OUT, JSON.stringify(cur, null, 2));
}

for (const lang of ['en', 'ur'] as const) {
  test(`LCP on /${lang}/ is under 2.5 s with 4x CPU slowdown`, async ({ page, request }) => {
    await mock(request, {});
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    await page.goto(`/${lang}/`, { waitUntil: 'load' });
    const lcp = await page.evaluate(
      () =>
        new Promise<number>((resolve) => {
          let last = 0;
          new PerformanceObserver((list) => {
            for (const e of list.getEntries()) last = e.startTime;
          }).observe({ type: 'largest-contentful-paint', buffered: true });
          setTimeout(() => resolve(last), 1500);
        }),
    );
    record(`lcp_${lang}_ms`, Math.round(lcp));
    expect(lcp).toBeGreaterThan(0);
    expect(lcp).toBeLessThan(2500);
  });
}

test('frame time during a run (sample)', async ({ page, request }) => {
  await mock(request, { speed: 1 });
  await page.goto('/en/');
  await page.keyboard.press('Escape');
  await page.getByTestId('run').click();
  const frames = await page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const out: number[] = [];
        let prev = performance.now();
        const end = prev + 3000;
        const tick = (t: number) => {
          out.push(t - prev);
          prev = t;
          if (t < end) requestAnimationFrame(tick);
          else resolve(out);
        };
        requestAnimationFrame(tick);
      }),
  );
  const sorted = [...frames].sort((a, b) => a - b);
  const p95 = sorted[Math.floor(sorted.length * 0.95)] ?? 0;
  const mean = frames.reduce((a, b) => a + b, 0) / Math.max(1, frames.length);
  record('frame_ms', { mean: Number(mean.toFixed(1)), p95: Number(p95.toFixed(1)), n: frames.length });
  // Informational: headless Chromium without a GPU throttles rAF, so this is not the 60 fps check (that is manual).
  expect(frames.length).toBeGreaterThan(0);
});
