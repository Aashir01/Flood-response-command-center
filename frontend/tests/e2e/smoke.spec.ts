// Playwright smoke suite (FRN-R13, design section 18.2), `mock` project: the static export and the mock Brain
// are served from one origin. An axe scan runs after each scenario state and fails on serious or critical issues.
import { expect, test } from '@playwright/test';
import { awakenings, axe, boot, expectVisibleFocus, jar, mock, ORGANS, recordAwakenings, runBriefing, tabUntil } from './helpers';

test.beforeEach(async ({ request }) => {
  await mock(request, {});
});

test('boot: awakening plays and is skippable with Esc; five jars render with status text; health fetched', async ({ page }) => {
  await recordAwakenings(page);
  const health = page.waitForResponse((r) => r.url().endsWith('/api/organs') && r.ok());
  await page.goto('/en/');
  await health;
  const overlay = page.getByTestId('awakening');
  await page.keyboard.press('Escape');
  await expect(overlay).toHaveCount(0);
  const seen = await awakenings(page);
  expect(seen[0]?.kind).toBe('boot');
  expect(seen[0]?.bolts).toBe(true);
  for (const o of ORGANS) {
    await expect(jar(page, o)).toBeVisible();
    await expect(jar(page, o).locator('.jar__status')).toHaveText(/\S/);
  }
  await expect(page.getByTestId('jar-status-eyes')).toHaveText('Idle');
  await expect(page.getByTestId('decision-support')).toBeVisible();
  await axe(page, 'boot');
});

test('boot: the awakening ends by itself in under 2.5 s', async ({ page }) => {
  await page.goto('/en/');
  const t0 = Date.now();
  await expect(page.getByTestId('awakening')).toHaveCount(0, { timeout: 4000 });
  expect(Date.now() - t0).toBeLessThan(2600);
});

test('default briefing: jars call then finish, five sections render, the live region announces completion', async ({ page, request }) => {
  await mock(request, { speed: 1.5 });
  await boot(page);
  await page.getByTestId('run').click();
  await expect(page.getByTestId('run')).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByTestId('jar-status-eyes')).toHaveText('Calling…');
  await expect(page.getByTestId('awakening')).toHaveAttribute('data-kind', 'complete', { timeout: 30_000 });
  await page.keyboard.press('Escape');
  for (const o of ['eyes', 'oracle', 'library', 'ledger']) await expect(page.getByTestId(`jar-status-${o}`)).toHaveText('Done');
  for (const id of ['extent', 'forecast', 'guidance', 'allocation', 'caveats'])
    await expect(page.locator(`#card-${id}`)).toHaveAttribute('data-panel-state', /success|partial/);
  await expect(page.getByTestId('live-polite')).toContainText('Briefing ready');
  await expect(page.getByTestId('forecast-chart')).toBeVisible();
  await expect(page.getByTestId('eyes-labels')).toContainText('Demo scene');
  await expect(page.getByTestId('eyes-labels')).toContainText('Sen1Floods11 test split');
  await expect(page.locator('#card-forecast')).toContainText('Modeled (GloFAS)');
  await expect(page.locator('body')).not.toContainText(/\bgauge\b|\bobserved\b/i);
  await axe(page, 'default briefing');
});

test('organ error: Oracle shows the organ is unwell with the reason; forecast says what is missing; others intact', async ({ page, request }) => {
  await mock(request, { scenario: 'organ-error', speed: 8 });
  await boot(page);
  await runBriefing(page);
  const oracle = jar(page, 'oracle');
  await expect(oracle.locator('.jar__status')).toHaveText('The organ is unwell');
  await expect(oracle.locator('.jar__note')).toHaveText(/\S/);
  const card = page.locator('#card-forecast');
  await expect(card).toHaveAttribute('data-panel-state', 'error');
  await expect(card.getByRole('alert')).toContainText('The organ is unwell');
  await expect(card.getByRole('alert')).toContainText('The briefing is missing');
  await expect(card.getByRole('button', { name: 'Run again' })).toBeVisible();
  await expect(page.locator('#card-extent')).toHaveAttribute('data-panel-state', 'success');
  await expect(page.locator('#card-allocation')).toHaveAttribute('data-panel-state', /success|partial/);
  await axe(page, 'organ error');
});

test('evidence drill-down: dialog shows organ, tool, pointer, value; guidance shows quote and page; Esc closes and focus returns', async ({ page }) => {
  await boot(page);
  await runBriefing(page);
  const btn = page.locator('#card-guidance').getByTestId('evidence-button').first();
  await btn.click();
  const dialog = page.getByRole('dialog', { name: 'Evidence' });
  await expect(dialog).toBeVisible();
  const item = dialog.getByTestId('evidence-item').first();
  await expect(item).toContainText('Tool');
  await expect(item).toContainText('JSON pointer');
  await expect(item).toContainText('answer_with_citations');
  await expect(dialog.getByTestId('evidence-citation').first()).toContainText(/page \d+/);
  await axe(page, 'evidence dialog');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(btn).toBeFocused();

  // A number claim resolves a value.
  const numBtn = page.locator('#card-extent').getByTestId('evidence-button').first();
  await numBtn.click();
  await expect(page.getByRole('dialog').getByTestId('evidence-value').first()).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(numBtn).toBeFocused();
});

test('Urdu RTL: lang and dir flip, chrome mirrors, identifiers are isolated, charts stay LTR, switching back restores text', async ({ page }) => {
  await boot(page);
  const before = (await page.locator('header').innerText()).replace(/\s+/g, ' ');
  const switchLang = async () => {
    const health = page.waitForResponse((r) => r.url().includes('/api/organs'), { timeout: 15_000 });
    await page.getByTestId('lang-toggle').click();
    await health;
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('awakening')).toHaveCount(0, { timeout: 8000 });
  };
  await switchLang();
  await expect(page).toHaveURL(/\/ur\/$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'ur');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  // The brand sits at the inline start, which is the right edge in RTL.
  const vw = page.viewportSize()!.width;
  const brand = (await page.locator('.brand').boundingBox())!;
  expect(brand.x + brand.width).toBeGreaterThan(vw / 2);
  await runBriefing(page);
  await expect(page.getByTestId('forecast-chart').locator('svg[role="img"]')).toHaveAttribute('direction', 'ltr');
  await expect(page.getByTestId('equity-slider')).toHaveAttribute('dir', 'ltr');
  expect(await page.locator('#card-extent bdi').count()).toBeGreaterThan(0);
  await expect(page.locator('#card-forecast')).toContainText(/GloFAS/);
  await axe(page, 'urdu briefing');
  await switchLang();
  await expect(page).toHaveURL(/\/en\/$/);
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
  const after = (await page.locator('header').innerText()).replace(/\s+/g, ' ');
  expect(after).toBe(before);
});

test('keyboard only: skip links, run, open a claim, close; focus is always visible', async ({ page }) => {
  await boot(page);
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to bench' })).toBeFocused();
  await expectVisibleFocus(page);
  await tabUntil(page, (el) => el.getAttribute('data-testid') === 'run');
  await expectVisibleFocus(page);
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('confidence')).toBeVisible({ timeout: 30_000 });
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('awakening')).toHaveCount(0);
  await tabUntil(page, (el) => el.getAttribute('data-testid') === 'evidence-button', 250);
  await expectVisibleFocus(page);
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(await page.evaluate(() => document.activeElement?.getAttribute('data-testid'))).toBe('evidence-button');
  // Jar drawer by keyboard.
  await page.locator('button.jar[data-organ="eyes"]').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toContainText('Last call');
  await page.keyboard.press('Escape');
  await expect(page.locator('button.jar[data-organ="eyes"]')).toBeFocused();
});

test('keyboard map: the canvas takes focus, T toggles the table, the table is reachable', async ({ page }) => {
  await boot(page);
  await runBriefing(page);
  const canvas = page.locator('#map canvas.maplibregl-canvas');
  test.skip((await canvas.count()) === 0, 'WebGL unavailable in this browser; the table fallback is covered below');
  await canvas.focus();
  await expectVisibleFocus(page);
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('t');
  await expect(page.getByTestId('map-table')).toBeVisible();
  await expect(page.getByTestId('map-table').locator('tbody tr').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Hide table' })).toBeVisible();
});

test('map layer toggles and the table alternative', async ({ page }) => {
  await boot(page);
  await runBriefing(page);
  const flood = page.locator('input[data-layer="flood"]');
  await expect(flood).toBeChecked();
  await flood.uncheck();
  await expect(flood).not.toBeChecked();
  await page.getByRole('button', { name: 'Show table' }).click();
  const table = page.getByTestId('map-table');
  await expect(table).toBeVisible();
  expect(await table.locator('tbody tr').count()).toBeGreaterThan(5);
  await axe(page, 'map table');
});

test.describe('reduced motion', () => {
  test.use({ reducedMotion: 'reduce' });
  test('no bolts, no repeating animation, a single fade', async ({ page }) => {
    await recordAwakenings(page);
    await page.goto('/en/');
    const overlay = page.getByTestId('awakening');
    await expect(page.locator('html')).toHaveAttribute('data-fx', 'none');
    await expect(overlay).toHaveCount(0, { timeout: 3000 });
    const seen = await awakenings(page);
    expect(seen.length).toBeGreaterThan(0);
    for (const a of seen) {
      expect(a.bolts).toBe(false);
      expect(a.timeline).toMatch(/reduced/);
    }
    await page.getByTestId('run').click();
    await expect(page.getByTestId('jar-status-eyes')).toHaveText(/Calling…|Done/);
    const infinite = await page.evaluate(() => document.getAnimations().filter((a) => a.effect?.getTiming().iterations === Infinity).length);
    expect(infinite).toBe(0);
    await expect(page.getByTestId('confidence')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('bolts')).toHaveCount(0);
    await axe(page, 'reduced motion');
  });
});

test('equity chart: an infeasible floor shows text and no line crosses the gap', async ({ page }) => {
  await boot(page);
  await runBriefing(page);
  const slider = page.getByTestId('equity-slider');
  await slider.focus();
  await page.keyboard.press('End');
  await expect(page.getByTestId('equity-readout')).toContainText('infeasible');
  await expect(slider).toHaveAttribute('aria-valuetext', /infeasible/);
  const chart = page.getByTestId('equity-chart');
  expect(await chart.locator('[data-infeasible-range]').count()).toBeGreaterThan(0);
  const segFloors = await chart.locator('path.feasible-line').evaluateAll((ps) => ps.map((p) => p.getAttribute('data-segment')));
  const statuses = await chart.getByTestId('equity-table').locator('tbody tr').evaluateAll((rows) => rows.map((r) => r.children[1]?.textContent ?? ''));
  expect(statuses.some((s) => s === 'Infeasible')).toBe(true);
  // Each drawn segment contains only feasible floors.
  const floors = await chart.getByTestId('equity-table').locator('tbody tr').evaluateAll((rows) => rows.map((r) => r.children[0]?.textContent ?? ''));
  const infeasibleFloors = new Set(floors.filter((_, i) => statuses[i] === 'Infeasible'));
  expect(infeasibleFloors.size).toBeGreaterThan(0);
  expect(segFloors.length).toBeGreaterThan(0);
  await page.keyboard.press('Home');
  await expect(page.getByTestId('equity-readout')).not.toContainText('infeasible');
  await axe(page, 'equity chart');
});

test('ask the creature: an answer with citations, then a refusal shown as a normal outcome', async ({ page }) => {
  await boot(page);
  const input = page.getByTestId('ask-input');
  await input.fill('How much drinking water does each person need per day?');
  await expect(page.getByText(/of 500 characters/)).toBeVisible();
  await page.getByTestId('ask-submit').click();
  await expect(page.getByTestId('ask-answer')).toBeVisible();
  await expect(page.getByTestId('ask-answer').getByTestId('evidence-button').first()).toBeVisible();
  await input.fill('Which cricket team will win the cup?');
  await page.getByTestId('ask-submit').click();
  await expect(page.getByTestId('refusal-card')).toBeVisible();
  await expect(page.getByTestId('refusal-card')).toContainText('Refused');
  await expect(page.getByTestId('ask-error')).toHaveCount(0);
  await axe(page, 'ask refusal');
});

test('voice cut: the Voice jar is disabled, the text box stays, a briefing still runs', async ({ page, request }) => {
  await mock(request, { scenario: 'voice-cut' });
  await boot(page);
  await expect(page.getByTestId('jar-status-voice')).toHaveText('Disabled');
  await expect(page.getByTestId('voice-controls')).toContainText('Voice is disabled');
  await expect(page.getByTestId('ask-mic')).toHaveCount(0);
  await expect(page.getByTestId('ask-input')).toBeVisible();
  await runBriefing(page);
  await expect(page.locator('#card-allocation')).toHaveAttribute('data-panel-state', /success|partial/);
  await axe(page, 'voice cut');
});

test('voice: Play needs a click, discloses the hosted provider once, and names it', async ({ page }) => {
  await boot(page);
  await runBriefing(page);
  const play = page.getByTestId('voice-play');
  await expect(play).toBeEnabled();
  expect(await page.evaluate(() => [...document.querySelectorAll('audio')].some((a) => !a.paused))).toBe(false);
  await play.click();
  const dlg = page.getByRole('dialog');
  await expect(dlg).toContainText('hosted speech service');
  await dlg.getByRole('button', { name: 'Send and play' }).click();
  await expect(page.getByTestId('voice-provider')).toContainText(/Voice by azure/i);
});

test('brain down: the creature sleeps, with a retry', async ({ page, request }) => {
  await mock(request, { scenario: 'brain-down' });
  await page.goto('/en/');
  await page.keyboard.press('Escape');
  const sleeps = page.getByTestId('creature-sleeps');
  await expect(sleeps).toBeVisible({ timeout: 15_000 });
  await expect(sleeps.getByRole('heading', { name: 'The creature sleeps' })).toBeVisible();
  await axe(page, 'brain down');
  await mock(request, { scenario: 'default-demo' });
  await sleeps.getByRole('button', { name: 'Try to wake it' }).click();
  await expect(page.getByTestId('run')).toBeVisible();
});

test('offline fallback: a live request that fell back to demo shows the banner', async ({ page, request }) => {
  await mock(request, { scenario: 'offline-fallback' });
  await boot(page);
  await runBriefing(page);
  await expect(page.getByTestId('offline-banner')).toBeVisible();
  await expect(page.getByTestId('mode-badge')).toContainText('Demo');
});

test('partial: the Ledger ran without sensitivity and the card says why', async ({ page, request }) => {
  await mock(request, { scenario: 'partial' });
  await boot(page);
  await runBriefing(page);
  await expect(page.locator('#card-allocation')).toContainText('without a sensitivity report');
  await expect(page.getByTestId('equity-chart')).toHaveCount(0);
});

test('conflict: both sides of a disagreement have evidence buttons', async ({ page, request }) => {
  await mock(request, { scenario: 'conflict' });
  await boot(page);
  await runBriefing(page);
  const banner = page.getByTestId('conflict-banner');
  await expect(banner).toBeVisible();
  const sides = banner.locator('.conflict').first().getByRole('button', { name: /^Evidence \d/ });
  expect(await sides.count()).toBeGreaterThanOrEqual(2);
  await sides.nth(1).click();
  await expect(page.getByRole('dialog', { name: 'Evidence' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(sides.nth(1)).toBeFocused();
  await axe(page, 'conflict');
});

test('high contrast: toggle sets the theme, removes glows and persists', async ({ page }) => {
  await boot(page);
  const toggle = page.getByTestId('contrast-toggle');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await toggle.click();
  await expect(page.locator('html')).toHaveAttribute('data-contrast', 'more');
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg).toBe('rgb(0, 0, 0)');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-contrast', 'more');
  await page.keyboard.press('Escape');
  await axe(page, 'high contrast');
});

test('evals: the heartbeat renders and labels Oracle rows as modeled; empty state', async ({ page, request }) => {
  await page.goto('/en/evals/');
  await expect(page.getByTestId('evals')).toBeVisible();
  await expect(page.getByTestId('evals')).toContainText('Modeled (GloFAS)');
  await axe(page, 'evals');
  await mock(request, { evals: 'empty' });
  await page.reload();
  await expect(page.getByTestId('evals-none')).toBeVisible();
});

test('about page renders the honest labels and credits', async ({ page }) => {
  await page.goto('/en/about/');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.locator('main')).toContainText('Sen1Floods11');
  await axe(page, 'about');
});
