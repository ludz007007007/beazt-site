// Verify /my-keys renders (login-gated) with the keys.html edits.
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 320, height: 680 }, reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  const errs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 200)); });
  page.on('pageerror', e => errs.push('pageerror: ' + String(e).slice(0, 200)));
  await page.goto('http://127.0.0.1:5000/auth/login', { waitUntil: 'load' });
  await page.fill('input[name="username"]', 'checkout-tester').catch(() => page.fill('input[type="text"]', 'checkout-tester'));
  await page.fill('input[type="password"]', 'CheckoutTest123!');
  await page.evaluate(() => document.getElementById('login-form') ? document.getElementById('login-form').requestSubmit() : document.querySelector('form').requestSubmit());
  await page.waitForLoadState('load');
  await page.waitForTimeout(1000);
  const url = page.url();
  const resp = await page.goto('http://127.0.0.1:5000/my-keys', { waitUntil: 'load' });
  await page.waitForTimeout(1500);
  const info = await page.evaluate(() => {
    const grids = document.querySelectorAll('.keys-grid').length;
    const setupLinks = Array.from(document.querySelectorAll('a')).filter(a => a.textContent.includes('Setup Guide')).map(a => a.getAttribute('href'));
    const skeletonCards = document.querySelectorAll('.skeleton-license-card').length;
    return { keysGridCount: grids, setupLinks, skeletonCards, hasT1: !!document.querySelector('.t-h1'), body: document.body.innerText.slice(0, 120) };
  }).catch(e => ({ error: String(e) }));
  await page.screenshot({ path: __dirname + '/my-keys-320.png', fullPage: true });
  console.log('login landed on:', url);
  console.log('my-keys status:', resp ? resp.status() : 'n/a');
  console.log('info:', JSON.stringify(info, null, 1));
  console.log('console errors:', errs.length ? errs.join(' | ') : 'none');
  await browser.close();
})();
