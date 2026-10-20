// Verification for /feedback (proof-reviews-page feature, 2026-09-15)
// Renders the LIVE Flask page (http://127.0.0.1:5000/feedback) in headless
// Chromium, checks console errors, horizontal overflow at 320/390/768/1440,
// keyboard focus of CTAs, and saves screenshots to evidence/feedback/.
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

// verify.js lives inside evidence/feedback/, so the repo root is two levels up.
const OUT = path.join(__dirname, '..', '..', 'evidence', 'feedback');
const VIEWPORTS = [
  { name: 'mobile-320', width: 320, height: 720 },
  { name: 'mobile-390', width: 390, height: 844 },
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'desktop-1440', width: 1440, height: 900 },
];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const results = { url: 'http://127.0.0.1:5000/feedback', viewports: [], consoleErrors: [], dom: {} };

  // DOM facts at desktop viewport
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('console', (msg) => { if (msg.type() === 'error') results.consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => results.consoleErrors.push('pageerror: ' + err.message));
  await page.goto(results.url, { waitUntil: 'networkidle' });

  results.dom.emptyState = await page.locator('.empty-state[role="status"]').count();
  results.dom.emptyTitle = (await page.locator('.empty-title').first().innerText().catch(() => '')).trim();
  results.dom.reviewCards = await page.locator('.review-card').count();
  results.dom.ratingSummary = await page.locator('.rating-summary').count();
  results.dom.proofCards = await page.locator('.proof-card').count();
  results.dom.fabricatedNames = [];
  for (const name of ['Kai', 'VeteranRust', 'Mason', 'DeltaX', 'ZeroDay', 'ScopedIn']) {
    if (await page.getByText(name, { exact: false }).count()) results.dom.fabricatedNames.push(name);
  }
  const discordCta = page.getByRole('link', { name: 'Ask buyers in Discord' });
  results.dom.discordCta = await discordCta.count();
  results.dom.discordHref = results.dom.discordCta ? await discordCta.first().getAttribute('href') : null;
  const browseCta = page.getByRole('link', { name: 'Browse products' });
  results.dom.browseCta = await browseCta.count();
  results.dom.browseHref = results.dom.browseCta ? await browseCta.first().getAttribute('href') : null;

  // Keyboard: tab to CTAs, confirm focus visibility
  await page.keyboard.press('Tab');
  const focused = await page.evaluate(() => document.activeElement.textContent.trim());
  results.dom.firstTabFocus = focused;

  // Lucide icons rendered (data-lucide replaced by svg)
  await page.waitForTimeout(800);
  results.dom.emptyStateIconSvg = await page.locator('.empty-icon svg').count();

  await page.screenshot({ path: path.join(OUT, 'desktop-1440.png'), fullPage: true });
  await page.close();

  // Overflow check per viewport
  for (const vp of VIEWPORTS) {
    const p = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
    p.on('console', (msg) => { if (msg.type() === 'error') results.consoleErrors.push(`[${vp.name}] ` + msg.text()); });
    p.on('pageerror', (err) => results.consoleErrors.push(`[${vp.name}] pageerror: ` + err.message));
    await p.goto(results.url, { waitUntil: 'networkidle' });
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    results.viewports.push({ ...vp, horizontalOverflowPx: overflow });
    await p.screenshot({ path: path.join(OUT, `${vp.name}.png`), fullPage: true });
    await p.close();
  }

  await browser.close();
  fs.writeFileSync(path.join(OUT, 'VAL-PROOF-results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
})().catch((e) => { console.error('VERIFY FAILED:', e); process.exit(1); });
