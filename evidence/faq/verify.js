// Verification for /faq (faq-page feature, 2026-09-16)
// Renders the LIVE Flask page (http://127.0.0.1:5000/faq) in headless
// Chromium with reduced motion (ScrollReveal bug workaround per AGENTS.md),
// checks VAL-FAQ-001/002/003: all 10 questions + 4 category headers,
// accordion expand/collapse, search filter, deep-link auto-open of
// #faq-answer-N, keyboard nav, zero console errors, no horizontal overflow
// at 320/390/768/1440, and saves screenshots to evidence/faq/.
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

// verify.js lives inside evidence/faq/, so the repo root is two levels up.
const OUT = path.join(__dirname, '..', '..', 'evidence', 'faq');
const VIEWPORTS = [
  { name: 'mobile-320', width: 320, height: 720 },
  { name: 'mobile-390', width: 390, height: 844 },
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'desktop-1440', width: 1440, height: 900 },
];
const EXPECTED_IDS = Array.from({ length: 10 }, (_, i) => `faq-answer-${i + 1}`);
const EXPECTED_GROUPS = ['Before you buy', 'Buy & payment', 'Delivery & setup', 'Updates & Discord support'];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const results = { url: 'http://127.0.0.1:5000/faq', viewports: [], consoleErrors: [], dom: {}, interactions: {} };

  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    reducedMotion: 'reduce',
  });
  page.on('console', (msg) => { if (msg.type() === 'error') results.consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => results.consoleErrors.push('pageerror: ' + err.message));
  await page.goto(results.url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);

  // VAL-FAQ-001: all questions + categories
  results.dom.itemCount = await page.locator('.faq-groups .faq-item').count();
  results.dom.answerIds = await page.locator('.faq-groups .faq-answer').evaluateAll((els) => els.map((e) => e.id));
  results.dom.missingIds = EXPECTED_IDS.filter((id) => !results.dom.answerIds.includes(id));
  results.dom.groupCount = await page.locator('.faq-group').count();
  results.dom.groupTitles = await page.locator('.faq-group-title').evaluateAll((els) => els.map((e) => e.textContent.trim()));
  results.dom.missingGroups = EXPECTED_GROUPS.filter(
    (g) => !results.dom.groupTitles.some((t) => t.toLowerCase().includes(g.toLowerCase().split(' ')[0]))
  );
  results.dom.questionCount = await page.locator('.faq-question').count();
  results.dom.ariaControlsOk = await page.locator('.faq-question').evaluateAll((btns) =>
    btns.every((b) => document.getElementById(b.getAttribute('aria-controls')) !== null)
  );

  // VAL-FAQ-002: accordion expand/collapse (exclusive: opening one closes others)
  const firstBtn = page.locator('.faq-groups .faq-question').first();
  await firstBtn.click();
  await page.waitForTimeout(400);
  results.interactions.firstOpen =
    (await page.locator('.faq-groups .faq-item.open').count()) === 1 &&
    (await firstBtn.getAttribute('aria-expanded')) === 'true';
  const secondBtn = page.locator('.faq-groups .faq-question').nth(1);
  await secondBtn.click();
  await page.waitForTimeout(400);
  results.interactions.exclusiveToggle =
    (await page.locator('.faq-groups .faq-item.open').count()) === 1 &&
    (await secondBtn.getAttribute('aria-expanded')) === 'true' &&
    (await firstBtn.getAttribute('aria-expanded')) === 'false';
  await secondBtn.click();
  await page.waitForTimeout(400);
  results.interactions.collapseToggle =
    (await page.locator('.faq-groups .faq-item.open').count()) === 0 &&
    (await secondBtn.getAttribute('aria-expanded')) === 'false';

  // VAL-FAQ-003: search filter
  const search = page.locator('#faq-search');
  results.dom.searchPresent = (await search.count()) === 1;
  await search.fill('refund');
  await page.waitForTimeout(300);
  results.interactions.searchVisible = await page.locator('.faq-groups .faq-item:not(.is-hidden)').count();
  results.interactions.searchKeepsRefund = await page.locator('.faq-item:has(#faq-answer-9):not(.is-hidden)').count();
  results.interactions.searchCountText = (await page.locator('#faq-search-count').innerText()).trim();
  await page.locator('#faq-clear-search').dispatchEvent('click');
  await page.waitForTimeout(300);
  results.interactions.searchCleared = await page.locator('.faq-groups .faq-item:not(.is-hidden)').count();
  await search.fill('zzz-no-such-question');
  await page.waitForTimeout(300);
  results.interactions.emptyStateVisible = await page.locator('#faq-empty:not(.is-hidden)').count();
  await search.fill('');
  await page.waitForTimeout(300);

  // Deep-link: #faq-answer-5 auto-opens on load
  await page.goto(results.url + '#faq-answer-5', { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  results.interactions.deepLinkOpen = await page.locator('.faq-item:has(#faq-answer-5).open').count();
  results.interactions.deepLinkAria = await page.locator('.faq-question[aria-controls="faq-answer-5"]').getAttribute('aria-expanded');

  // Keyboard: focus search, tab to first question, Enter toggles
  await page.goto(results.url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  await page.locator('#faq-search').focus();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  const kbFocused = await page.evaluate(() => document.activeElement.className || '');
  results.interactions.keyboardFocusClass = kbFocused;
  await page.keyboard.press('Enter');
  await page.waitForTimeout(400);
  results.interactions.keyboardToggle = await page.locator('.faq-groups .faq-item.open').count();

  // Collapsed leak check: closed answers must have ~zero visible height
  results.interactions.collapsedHeights = await page.locator('.faq-groups .faq-answer').evaluateAll((els) =>
    els.map((e) => Math.round(e.getBoundingClientRect().height))
  );

  await page.screenshot({ path: path.join(OUT, 'desktop-1440.png'), fullPage: true });

  // Overflow check per viewport
  for (const vp of VIEWPORTS) {
    const p = await browser.newPage({
      viewport: { width: vp.width, height: vp.height },
      reducedMotion: 'reduce',
    });
    p.on('console', (msg) => { if (msg.type() === 'error') results.consoleErrors.push(`[${vp.name}] ` + msg.text()); });
    p.on('pageerror', (err) => results.consoleErrors.push(`[${vp.name}] pageerror: ` + err.message));
    await p.goto(results.url, { waitUntil: 'networkidle' });
    await p.waitForTimeout(400);
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    results.viewports.push({ ...vp, horizontalOverflowPx: overflow });
    await p.screenshot({ path: path.join(OUT, `${vp.name}.png`), fullPage: true });
    await p.close();
  }

  await browser.close();
  fs.writeFileSync(path.join(OUT, 'VAL-FAQ-results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
})().catch((e) => { console.error('VERIFY FAILED:', e); process.exit(1); });
