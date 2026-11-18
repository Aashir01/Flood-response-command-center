// Shared Playwright helpers for the `mock` project (static export + mock Brain on one origin).
import AxeBuilder from '@axe-core/playwright';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

export type Scenario =
  | 'default-demo'
  | 'conflict'
  | 'organ-error'
  | 'refusal'
  | 'partial'
  | 'slow'
  | 'voice-cut'
  | 'offline-fallback'
  | 'brain-down';

/** Switch the mock Brain's scenario (the mock is one process, so tests run with one worker). */
export async function mock(request: APIRequestContext, cfg: { scenario?: Scenario; speed?: number; evals?: 'full' | 'empty' | 'stale' | 'partial' }) {
  const r = await request.post('/__mock/config', { data: { scenario: 'default-demo', speed: 4, evals: 'full', ...cfg } });
  expect(r.ok()).toBe(true);
}

export const ORGANS = ['Eyes', 'Oracle', 'Library', 'Ledger', 'Voice'] as const;

export const jar = (page: Page, name: (typeof ORGANS)[number] | string) => page.locator(`button.jar[data-organ="${name.toLowerCase()}"]`);

/**
 * Records every awakening overlay that appears (kind, timeline, whether bolts were drawn), so short
 * timelines can be asserted after they have already ended. Read with `awakenings(page)`.
 */
export async function recordAwakenings(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __awk: { kind: string | null; timeline: string | null; bolts: boolean }[] };
    w.__awk = [];
    const seen = new WeakSet<Element>();
    new MutationObserver(() => {
      const el = document.querySelector('[data-testid="awakening"]');
      if (el && !seen.has(el)) {
        seen.add(el);
        w.__awk.push({ kind: el.getAttribute('data-kind'), timeline: el.getAttribute('data-timeline'), bolts: !!el.querySelector('[data-testid="bolts"]') });
      }
    }).observe(document, { subtree: true, childList: true });
  });
}
export const awakenings = (page: Page) =>
  page.evaluate(() => (window as unknown as { __awk: { kind: string | null; timeline: string | null; bolts: boolean }[] }).__awk);

/** Load a page and skip the boot awakening with Esc. */
export async function boot(page: Page, path = '/en/') {
  // Wait for hydration (the boot health fetch), then skip; the overlay may already have ended on a slow machine.
  const health = page.waitForResponse((r) => r.url().includes('/api/organs'), { timeout: 15_000 }).catch(() => undefined);
  await page.goto(path);
  await health;
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('awakening')).toHaveCount(0, { timeout: 8000 });
}

/** Press Run and wait for the briefing; skips the completion awakening. */
export async function runBriefing(page: Page) {
  await page.getByTestId('run').click();
  await expect(page.getByTestId('confidence')).toBeVisible({ timeout: 30_000 });
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('awakening')).toHaveCount(0);
}

/** axe scan; fails on serious or critical violations (FRN-R13.2). */
export async function axe(page: Page, label: string) {
  const res = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).exclude('.maplibregl-canvas').analyze();
  const bad = res.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  const text = bad.map((v) => `${v.id} (${v.impact}): ${v.help}\n  ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join('\n  ')}`).join('\n');
  expect(bad, `axe violations at "${label}":\n${text}`).toEqual([]);
}

/** Tab until `pred` holds for the focused element (keyboard-only paths). */
export async function tabUntil(page: Page, pred: (el: Element) => boolean, max = 120): Promise<void> {
  const src = pred.toString();
  for (let i = 0; i < max; i++) {
    await page.keyboard.press('Tab');
    const ok = await page.evaluate((s) => {
      const el = document.activeElement;
      return !!el && (new Function(`return (${s})`)() as (e: Element) => boolean)(el);
    }, src);
    if (ok) return;
  }
  throw new Error(`focus never matched after ${max} tabs: ${src}`);
}

/** The focused element shows a visible ring (outline or box-shadow), FRN-R11.1. */
export async function expectVisibleFocus(page: Page) {
  const style = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { outline: cs.outlineStyle, width: parseFloat(cs.outlineWidth), shadow: cs.boxShadow };
  });
  expect(style).not.toBeNull();
  expect(style!.outline !== 'none' && style!.width >= 2 ? true : style!.shadow !== 'none').toBe(true);
}
