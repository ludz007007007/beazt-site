// VAL-PERF-001: LCP + CLS on /, /cheats, product — unthrottled + slow-3G (CDP emulation)
const { chromium } = require('E:\\github\\rust beazt\\BEAZT-WEBSITE\\node_modules\\playwright');
const fs = require('fs');
const path = require('path');
const OUT = path.join(__dirname, 'cwv-results.json');
const BASE = 'http://127.0.0.1:5000';

const TARGETS = [
  { id: 'home', path: '/' },
  { id: 'cheats', path: '/cheats' },
  { id: 'product', path: '/product/rust-external-private' },
];

const SLOW3G = { offline: false, latency: 150, downloadThroughput: 40960 / 8, uploadThroughput: 10240 / 8 };

async function measure(ctx, cdp, page, path_, throttle) {
  if (throttle) {
    await cdp.send('Network.enable');
    await cdp.send('Network.emulateNetworkConditions', SLOW3G);
  }
  const t0 = Date.now();
  await page.goto(BASE + path_, { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(2500); // settle for CLS/LCP observations post-load
  const cwv = await page.evaluate(() => window.__cwv || null);
  const result = {
    lcpMs: cwv && cwv.lcp != null ? Math.round(cwv.lcp) : null,
    lcpElement: cwv ? cwv.lcpTag : null,
    cls: cwv ? Math.round(cwv.cls * 1000) / 1000 : null,
    wallMs: Date.now() - t0,
  };
  if (throttle) {
    await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  }
  return result;
}

(async () => {
  const results = {};
  const browser = await chromium.launch({ headless: true });

  for (const mode of ['unthrottled', 'slow3g']) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await ctx.addInitScript(() => {
      window.__cwv = { lcp: null, lcpTag: null, cls: 0 };
      try {
        new PerformanceObserver(list => {
          for (const e of list.getEntries()) {
            window.__cwv.lcp = e.startTime;
            window.__cwv.lcpTag = e.element ? e.element.tagName + '.' + (e.element.className || '').split(' ')[0] : null;
          }
        }).observe({ type: 'largest-contentful-paint', buffered: true });
      } catch (e) {}
      try {
        new PerformanceObserver(list => {
          for (const e of list.getEntries()) if (!e.hadRecentInput) window.__cwv.cls += e.value;
        }).observe({ type: 'layout-shift', buffered: true });
      } catch (e) {}
    });
    const page = await ctx.newPage();
    const cdp = await ctx.newCDPSession(page);
    results[mode] = {};
    for (const t of TARGETS) {
      results[mode][t.id] = await measure(ctx, cdp, page, t.path, mode === 'slow3g');
      console.log(mode, t.id, JSON.stringify(results[mode][t.id]));
    }
    await ctx.close();
  }
  fs.writeFileSync(OUT, JSON.stringify(results, null, 2));
  console.log('DONE');
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
