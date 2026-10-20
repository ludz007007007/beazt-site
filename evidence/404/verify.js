const { chromium } = require('E:\\github\\rust beazt\\BEAZT-WEBSITE\\node_modules\\playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const outDir = 'E:\\github\\rust beazt\\BEAZT-WEBSITE\\evidence\\404';
  fs.mkdirSync(outDir, { recursive: true });
  const results = { checks: [], consoleErrors: [], failedRequests: [] };
  const browser = await chromium.launch();
  // NO reducedMotion override: this run must prove the page is visible in a
  // normal default-motion browser (reveal load-order fix; .nf-card previously
  // sat inside a single .reveal wrapper and rendered blank).
  const page = await browser.newPage();
  const allResponses = [];
  page.on('response', r => allResponses.push(r.url()));
  page.on('console', m => { if (m.type() === 'error') results.consoleErrors.push(m.text()); });
  page.on('requestfailed', r => results.failedRequests.push(r.url() + ' :: ' + (r.failure() || {}).errorText));
  page.on('response', r => { if (r.status() >= 400 && !r.url().includes('fonts.g') && !r.url().includes('unpkg.com')) results.failedRequests.push(r.status + ' ' + r.url()); });

  // The test intentionally requests a missing document; its own HTTP 404 is
  // expected (mission-documented pattern). Filter it before the clean checks.
  const TEST_URL = 'definitely-not-a-real-page';
  const realConsoleErrors = () => results.consoleErrors.filter(e => !/status of 404/.test(e));
  const realFailedRequests = () => results.failedRequests.filter(e => !e.includes(TEST_URL));

  function check(name, ok, detail) {
    results.checks.push({ name, pass: !!ok, detail: detail || '' });
    console.log((ok ? 'PASS' : 'FAIL') + ' ' + name + (detail ? ' :: ' : '') + (detail || ''));
  }

  // ---- VAL-404-001: 404 page loads with error message and working links ----
  const resp = await page.goto('http://127.0.0.1:5000/definitely-not-a-real-page', { waitUntil: 'networkidle' });
  check('unknown URL returns HTTP 404', resp && resp.status() === 404, String(resp && resp.status()));
  check('title', (await page.title()).includes('Page Not Found'), await page.title());
  check('eyebrow Error 404', /error\s*404/i.test(await page.textContent('.section-eyebrow')), (await page.textContent('.section-eyebrow') || '').trim());
  check('decorative 404 code present', (await page.locator('.nf-code').count()) === 1, '');
  check('h1 Page not found', ((await page.textContent('h1')) || '').trim() === 'Page not found', (await page.textContent('h1') || '').trim());
  check('explanatory lead >= 40 chars', ((await page.textContent('.nf-lead')) || '').length >= 40, String(((await page.textContent('.nf-lead')) || '').length));
  // reveal load-order fix: .nf-card sits in a .reveal wrapper and must actually
  // reveal in a normal default-motion browser (previously stuck at opacity 0).
  const nfCard = await page.evaluate(() => {
    const el = document.querySelector('.nf-card');
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { hasVisible: el.classList.contains('visible'), opacity: cs.opacity, rectH: Math.round(el.getBoundingClientRect().height) };
  });
  check('.nf-card revealed in normal-motion browser', !!nfCard && nfCard.hasVisible && nfCard.opacity === '1' && nfCard.rectH > 0, JSON.stringify(nfCard));
  check('primary CTA Back to home -> /', (await page.getAttribute('a.btn-primary', 'href')) === '/', await page.getAttribute('a.btn-primary', 'href'));
  check('secondary CTA -> /cheats', (await page.getAttribute('a.btn-secondary', 'href')) === '/cheats', await page.getAttribute('a.btn-secondary', 'href'));
  const chips = await page.$$eval('.nf-chip', els => els.map(a => ({ text: a.textContent.trim(), href: a.getAttribute('href') })));
  check('4 quick-link chips', chips.length === 4, JSON.stringify(chips));
  check('chips hit real routes', chips.every(c => ['/faq', '/loader', '/feedback', '/my-keys'].includes(c.href)), JSON.stringify(chips.map(c => c.href)));

  // links actually navigate (JS click; synthetic mouse coords unreliable headless)
  await page.$eval('a.btn-primary', a => a.click());
  await page.waitForURL('**/');
  check('Back to home navigates to /', new URL(page.url()).pathname === '/', page.url());
  await page.goto('http://127.0.0.1:5000/definitely-not-a-real-page', { waitUntil: 'networkidle' });
  await page.$eval('a.nf-chip[href="/faq"]', a => a.click());
  await page.waitForURL('**/faq');
  check('FAQ chip navigates to /faq', new URL(page.url()).pathname === '/faq', page.url());
  await page.goto('http://127.0.0.1:5000/definitely-not-a-real-page', { waitUntil: 'networkidle' });
  results.consoleErrors.length = 0;
  results.failedRequests.length = 0;

  // premium styling facts (real stylesheet applied)
  const style = await page.evaluate(() => {
    const code = document.querySelector('.nf-code');
    const cs = getComputedStyle(code);
    const chip = document.querySelector('.nf-chip');
    return {
      codeFont: cs.fontFamily,
      codeClip: cs.webkitTextFillColor,
      chipBorder: getComputedStyle(chip).borderColor,
      chipRadius: getComputedStyle(chip).borderRadius,
      btnShadow: getComputedStyle(document.querySelector('.btn-primary')).boxShadow !== 'none',
      eyebrowBg: getComputedStyle(document.querySelector('.section-eyebrow')).backgroundColor
    };
  });
  check('mono display font on 404 code', style.codeFont.includes('JetBrains Mono'), style.codeFont);
  check('gradient text clip applied', style.codeClip === 'rgba(0, 0, 0, 0)', style.codeClip);
  check('chips styled (radius + token border)', style.chipRadius !== '0px' && style.chipBorder !== '0px none rgb(0, 0, 0)', style.chipRadius + ' / ' + style.chipBorder);
  check('primary button has glow shadow', style.btnShadow, '');
  check('eyebrow accent background', style.eyebrowBg !== 'rgba(0, 0, 0, 0)', style.eyebrowBg);

  // keyboard: skip link -> tab order reaches nav + CTAs
  await page.keyboard.press('Tab');
  const f1 = await page.evaluate(() => document.activeElement.className);
  check('first tab lands on skip link', /skip-link/.test(f1), f1);
  await page.focus('a.btn-primary');
  const focusRing = await page.evaluate(() => getComputedStyle(document.querySelector('a.btn-primary')).boxShadow);
  check('focus state styled on primary CTA', focusRing !== 'none', focusRing.slice(0, 80));

  // responsive: no horizontal overflow at required breakpoints, touch targets >= 44px mobile
  await page.screenshot({ path: path.join(outDir, 'VAL-404-desktop-1440.png'), fullPage: true });
  for (const w of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width: w, height: 900 });
    await page.goto('http://127.0.0.1:5000/definitely-not-a-real-page', { waitUntil: 'networkidle' });
    await page.waitForTimeout(600);
    const ov = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, bw: document.body.scrollWidth }));
    check('no overflow @' + w, ov.sw <= ov.cw + 1 && ov.bw <= ov.cw + 1, JSON.stringify(ov));
    if (w === 390) {
      const touch = await page.evaluate(() => {
        const h = el => Math.round(el.getBoundingClientRect().height);
        return { cta: h(document.querySelector('.nf-actions .btn-primary')), chip: h(document.querySelector('.nf-chip')), dir: getComputedStyle(document.querySelector('.nf-actions')).flexDirection };
      });
      check('mobile stacked full-width CTAs', touch.dir === 'column' && touch.cta >= 44, JSON.stringify(touch));
      check('mobile chips >= 44px', touch.chip >= 44, String(touch.chip));
      await page.screenshot({ path: path.join(outDir, 'VAL-404-mobile-390.png'), fullPage: true });
    }
    if (w === 320) await page.screenshot({ path: path.join(outDir, 'VAL-404-mobile-320.png'), fullPage: true });
  }
  check('zero console errors (excluding document 404)', realConsoleErrors().length === 0, JSON.stringify(realConsoleErrors().slice(0, 5)));
  check('zero failed requests (excluding document 404)', realFailedRequests().length === 0, JSON.stringify(realFailedRequests().slice(0, 5)));
  check('no unpkg/scrollreveal CDN dependency', !allResponses.some(u => /unpkg\.com|scrollreveal/i.test(u)), String(allResponses.filter(u => /unpkg\.com|scrollreveal/i.test(u)).length) + ' CDN hits');

  fs.writeFileSync(path.join(outDir, 'VAL-404-results.json'), JSON.stringify(results, null, 2));
  await browser.close();
  const failed = results.checks.filter(c => !c.pass);
  console.log('TOTAL ' + results.checks.length + ' FAILED ' + failed.length);
  process.exit(failed.length ? 1 : 0);
})();
