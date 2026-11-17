// Screenshots for the write-up and the visual polish pass: `npm run shots` (Playwright project `shots`).
// Writes docs/screenshots/<view>-<lang>-<width>.png. Not part of the smoke suite.
import { expect, test, type Page } from '@playwright/test';
import { resolve } from 'node:path';
import { boot, mock, runBriefing } from './helpers';

// Playwright runs from frontend/ (package.json is ESM, so there is no __dirname).
const DIR = resolve(process.cwd(), '..', 'docs', 'screenshots');
const shot = (page: Page, name: string, full = false) => page.screenshot({ path: `${DIR}/${name}.png`, fullPage: full, animations: 'disabled' });

const SIZES = [
  { tag: 'desktop', width: 1440, height: 900 },
  { tag: 'mobile', width: 360, height: 780 },
] as const;

for (const lang of ['en', 'ur'] as const) {
  for (const size of SIZES) {
    test(`views ${lang} ${size.tag}`, async ({ page, request }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await mock(request, { speed: 4 });
      await boot(page, `/${lang}/`);
      await shot(page, `bench-idle-${lang}-${size.tag}`);
      await runBriefing(page);
      // Let the map tiles and charts settle.
      await page.waitForTimeout(1200);
      await shot(page, `briefing-${lang}-${size.tag}`, true);
      await page.locator('#card-guidance').getByTestId('evidence-button').first().click();
      await expect(page.getByRole('dialog').getByTestId('evidence-item').first()).toBeVisible();
      await page.waitForTimeout(400);
      await shot(page, `evidence-${lang}-${size.tag}`);
      await page.keyboard.press('Escape');
      await page.goto(`/${lang}/evals/`);
      await expect(page.getByTestId('evals')).toBeVisible();
      await shot(page, `evals-${lang}-${size.tag}`, true);
    });
  }
}

test('states en desktop', async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mock(request, { speed: 0.6 });
  await page.goto('/en/');
  await page.waitForTimeout(1300);
  await shot(page, 'awakening-en-desktop');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('awakening')).toHaveCount(0);
  await page.getByTestId('run').click();
  await page.waitForTimeout(2500);
  await shot(page, 'running-en-desktop');
  await expect(page.getByTestId('confidence')).toBeVisible({ timeout: 30_000 });

  await mock(request, { scenario: 'organ-error', speed: 8 });
  await boot(page, '/en/');
  await runBriefing(page);
  await page.locator('#card-forecast').scrollIntoViewIfNeeded();
  await shot(page, 'organ-error-en-desktop');

  await mock(request, { scenario: 'conflict', speed: 8 });
  await boot(page, '/en/');
  await runBriefing(page);
  await page.getByTestId('conflict-banner').scrollIntoViewIfNeeded();
  await shot(page, 'conflict-en-desktop');

  await page.getByTestId('contrast-toggle').click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, 'high-contrast-en-desktop');
  await page.getByTestId('contrast-toggle').click();

  await mock(request, { scenario: 'brain-down' });
  await page.goto('/en/');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('creature-sleeps')).toBeVisible({ timeout: 15_000 });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  await shot(page, 'creature-sleeps-en-desktop');
  await mock(request, {});
});
