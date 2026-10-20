// VAL-PERF-002: loading="lazy" on images (product + store) — VAL-PERF-003: no external font/CDN requests
const { chromium } = require('E:\\github\\rust beazt\\BEAZT-WEBSITE\\node_modules\\playwright');
const fs = require('fs');
const path = require('path');
const OUT = path.join(__dirname, 'perf-network-results.json');
const BASE = 'http://127.0.0.1:5000';

const TARGETS = [
  { id: 'home', path: '/' },
  { id: 'cheats', path: '/cheats' },
  { id: 'product', path: '/product/rust-external-private' },
  { id: 'faq', path: '/faq' },
  { id: 'login', path: '/login' },
];

(async () => {
  const results = {};
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  for (const t of TARGETS) {
    const requests = [];
    const extReqs = [];
    const onReq = r => {
      const u = r.url();
      const rec = { type: r.resourceType(), url: u };
      requests.push(rec);
      try {
        const host = new URL(u).hostname;
        if (!['127.0.0.1', 'localhost'].includes(host)) {
          extReqs.push({ host, url: u, type: r.resourceType() });
        }
      } catch (e) {}
    };
    page.on('request', onReq);
    await page.goto(BASE + t.path, { waitUntil: 'networkidle', timeout: 60000 });
    await page.waitForTimeout(1500);

    // lazy attribute audit
    const imgAudit = await page.evaluate(() => {
      const imgs = Array.from(document.querySelectorAll('img'));
      return imgs.map(i => {
        const r = i.getBoundingClientRect();
        return {
          src: (i.currentSrc || i.src || '').replace(location.origin, ''),
          loading: i.getAttribute('loading'),
          inInitialViewport: r.top < innerHeight && r.bottom > 0,
        };
      });
    });
    // scroll to bottom to trigger lazy loads, then re-check requested images
    await page.mouse.wheel(0, 3000); await page.waitForTimeout(700);
    await page.mouse.wheel(0, 4000); await page.waitForTimeout(700);
    const imgAuditFull = await page.evaluate(() =>
      Array.from(document.querySelectorAll('img')).map(i => ({
        src: (i.currentSrc || i.src || '').replace(location.origin, ''),
        loading: i.getAttribute('loading'),
      }))
    );

    const fontReqs = requests.filter(r => r.type === 'font' || /\.woff2?|\.ttf|\.otf/i.test(r.url));
    const external = requests.filter(r => !r.url.startsWith(BASE) && !r.url.startsWith('data:'));

    results[t.id] = {
      path: t.path,
      totalRequests: requests.length,
      externalRequests: external.map(r => r.type + ' ' + r.url),
      externalFontOrCdn: extReqs.map(r => r.type + ' ' + r.url),
      fontRequests: fontReqs.map(r => r.url),
      imgAudit,
      imgAuditFull,
    };
    console.log(t.id, 'reqs=', requests.length, 'external=', external.length, 'fonts=', fontReqs.length, 'imgs=', imgAudit.length);
    page.off('request', onReq);
  }

  fs.writeFileSync(OUT, JSON.stringify(results, null, 2));
  console.log('DONE');
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
