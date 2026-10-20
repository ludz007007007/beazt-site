const { chromium } = require('E:\\github\\rust beazt\\BEAZT-WEBSITE\\node_modules\\playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const outDir = 'E:\\github\\rust beazt\\BEAZT-WEBSITE\\evidence\\loader';
  fs.mkdirSync(outDir, { recursive: true });
  const results = { checks: [], consoleErrors: [], failedRequests: [] };
  const browser = await chromium.launch();
  const page = await browser.newPage({ reducedMotion: 'reduce' });
  page.on('console', m => { if (m.type() === 'error') results.consoleErrors.push(m.text()); });
  page.on('requestfailed', r => results.failedRequests.push(r.url() + ' :: ' + (r.failure() || {}).errorText));
  page.on('response', r => { if (r.status() >= 400 && !r.url().includes('fonts.g')) results.failedRequests.push(r.status() + ' ' + r.url()); });

  function check(name, ok, detail) {
    results.checks.push({ name, pass: !!ok, detail: detail || '' });
    console.log((ok ? 'PASS' : 'FAIL') + ' ' + name + (detail ? ' :: ' + detail : ''));
  }

  // Generic /loader
  await page.goto('http://127.0.0.1:5000/loader', { waitUntil: 'networkidle' });
  check('generic 200 + title', (await page.title()).includes('Loader Setup'), await page.title());
  check('h1 Loader Guide', ((await page.textContent('h1')) || '').includes('Loader Guide'), await page.textContent('h1'));
  check('prerequisites list >=5', (await page.locator('.prereq-list li').count()) >= 5, String(await page.locator('.prereq-list li').count()));
  check('numbered steps =6', (await page.locator('.loader-guide-step').count()) === 6, String(await page.locator('.loader-guide-step').count()));
  check('download cards =3', (await page.locator('.loader-download-card').count()) === 3, String(await page.locator('.loader-download-card').count()));
  check('warn block', (await page.locator('.loader-callout--warn').count()) === 1, '');
  check('info block', (await page.locator('.loader-callout--info').count()) === 1, '');
  check('my-keys links', (await page.locator('a[href="/my-keys"]').count()) >= 3, String(await page.locator('a[href="/my-keys"]').count()));
  check('toc links', (await page.locator('.loader-toc a').count()) >= 3, String(await page.locator('.loader-toc a').count()));
  check('product guides list', (await page.locator('.loader-product-list a').count()) >= 1, String(await page.locator('.loader-product-list a').count()));
  // keyboard: tab to first My Keys link, focus visible
  await page.keyboard.press('Tab');
  const focused = await page.evaluate(() => document.activeElement ? document.activeElement.tagName + ':' + (document.activeElement.getAttribute('href') || document.activeElement.className) : 'none');
  check('keyboard focus lands', !!focused && focused !== 'none', focused);
  await page.screenshot({ path: path.join(outDir, 'VAL-LOADER-001-generic-desktop.png'), fullPage: true });

  // Product-specific
  await page.goto('http://127.0.0.1:5000/loader/rust-external-private', { waitUntil: 'networkidle' });
  check('product h1', ((await page.textContent('h1')) || '').includes('Rust External'), (await page.textContent('h1') || '').trim());
  check('product download card', (await page.getByText('Download for Rust External').count()) >= 1, '');
  check('product notes', (await page.getByText('Product notes').count()) >= 1, '');
  check('aria-current on product', (await page.locator('.loader-product-list a.is-current').count()) === 1, '');
  await page.screenshot({ path: path.join(outDir, 'VAL-LOADER-002-product-desktop.png'), fullPage: true });
  const cleanPagesConsoleErrors = results.consoleErrors.length;

  // 404 (intentionally loads a missing document — its own console 404 is
  // expected; reset the error log so only real page errors are counted)
  const r404 = await page.goto('http://127.0.0.1:5000/loader/does-not-exist', { waitUntil: 'domcontentloaded' });
  check('unknown slug 404', r404 && r404.status() === 404, String(r404 && r404.status()));
  results.consoleErrors.length = 0;

  // Overflow at viewports (generic page)
  for (const w of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width: w, height: 900 });
    await page.goto('http://127.0.0.1:5000/loader', { waitUntil: 'networkidle' });
    const ov = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, bw: document.body.scrollWidth }));
    check('no overflow @' + w, ov.sw <= ov.cw + 1 && ov.bw <= ov.cw + 1, JSON.stringify(ov));
    if (w === 390) await page.screenshot({ path: path.join(outDir, 'VAL-LOADER-001-mobile-390.png'), fullPage: true });
  }
  check('zero console errors', results.consoleErrors.length === 0, JSON.stringify(results.consoleErrors.slice(0, 5)));
  check('clean pages console errors', cleanPagesConsoleErrors === 0, String(cleanPagesConsoleErrors));

  fs.writeFileSync(path.join(outDir, 'VAL-LOADER-results.json'), JSON.stringify(results, null, 2));
  await browser.close();
  const failed = results.checks.filter(c => !c.pass);
  console.log('TOTAL ' + results.checks.length + ' FAILED ' + failed.length);
  process.exit(failed.length ? 1 : 0);
})();
