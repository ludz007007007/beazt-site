// store-followup-hardening verification: reveal system + Lucide hydration
// spot-checks on /, /feedback and a real product page against live flask-api.
const { chromium } = require('E:\\github\\rust beazt\\BEAZT-WEBSITE\\node_modules\\playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const outDir = 'E:\\github\\rust beazt\\BEAZT-WEBSITE\\evidence\\polish\\followup-hardening';
  fs.mkdirSync(outDir, { recursive: true });
  const results = { checks: [], consoleErrors: [], failedRequests: [] };
  const browser = await chromium.launch();
  // NO reducedMotion override: verify default-motion behavior end to end.
  const page = await browser.newPage();
  const allResponses = [];
  page.on('response', r => allResponses.push(r.url()));
  page.on('console', m => { if (m.type() === 'error') results.consoleErrors.push(m.text()); });
  page.on('requestfailed', r => results.failedRequests.push(r.url() + ' :: ' + (r.failure() || {}).errorText));

  function check(name, ok, detail) {
    results.checks.push({ name, pass: !!ok, detail: detail || '' });
    console.log((ok ? 'PASS' : 'FAIL') + ' ' + name + (detail ? ' :: ' : '') + (detail || ''));
  }

  async function inspectSurface(name, url, waitMs) {
    await page.goto(url, { waitUntil: 'networkidle' });
    if (waitMs) await page.waitForTimeout(waitMs);
    const state = await page.evaluate(() => {
      // lucide.createIcons() replaces each [data-lucide] placeholder span with
      // an <svg> carrying the same data-lucide attribute, so a hydrated icon is
      // either an svg itself or a holder containing an svg.
      const holders = Array.from(document.querySelectorAll('[data-lucide]'));
      const hydrated = holders.filter(h => h.tagName.toLowerCase() === 'svg' || h.querySelector('svg'));
      const reveals = Array.from(document.querySelectorAll('.reveal'));
      const vis = reveals.filter(el => el.classList.contains('visible'));
      const hidden = reveals.filter(el => !el.classList.contains('visible') && el.getBoundingClientRect().top < window.innerHeight && getComputedStyle(el).opacity === '0');
      return {
        lucideLoaded: !!(window.lucide && typeof window.lucide.createIcons === 'function'),
        lucideSpans: holders.length, svgSpans: hydrated.length,
        revealTotal: reveals.length, revealVisible: vis.length, revealStuckInViewport: hidden.length
      };
    });
    check(`${name}: lucide UMD loaded`, state.lucideLoaded, String(state.lucideLoaded));
    check(`${name}: every [data-lucide] placeholder hydrated to svg`, state.lucideSpans > 0 && state.svgSpans === state.lucideSpans, `${state.svgSpans}/${state.lucideSpans}`);
    check(`${name}: no .reveal element stuck invisible in viewport`, state.revealStuckInViewport === 0, `stuck=${state.revealStuckInViewport} visible=${state.revealVisible}/${state.revealTotal} (0 reveals = surface uses none)`);
    check(`${name}: zero console errors`, results.consoleErrors.length === 0, JSON.stringify(results.consoleErrors.slice(0, 3)));
    results.consoleErrors.length = 0;
    await page.screenshot({ path: path.join(outDir, `${name.replace(/[^a-z0-9-]/gi, '')}-top.png`), fullPage: false });
    return state;
  }

  // homepage
  await inspectSurface('home', 'http://127.0.0.1:5000/', 400);

  // feedback
  await inspectSurface('feedback', 'http://127.0.0.1:5000/feedback', 400);

  // discover a real product URL from /cheats, then inspect it
  await page.goto('http://127.0.0.1:5000/cheats', { waitUntil: 'networkidle' });
  const productHref = await page.evaluate(() => {
    const a = document.querySelector('a[href^="/product/"]');
    return a ? a.getAttribute('href') : null;
  });
  check('product link found on /cheats', !!productHref, productHref || 'none');
  if (productHref) {
    const state = await inspectSurface('product', 'http://127.0.0.1:5000' + productHref, 400);

    // cheat_image behavior on the live server for this product: with
    // redirect:'follow' a valid static image_url resolves to an image response.
    const slug = productHref.split('/').pop();
    const img = await page.evaluate(async (slug) => {
      const r = await fetch('/cheat-image/' + slug, { redirect: 'follow' });
      return { status: r.status, contentType: r.headers.get('content-type'), finalUrl: r.url };
    }, slug);
    check(`live /cheat-image/${slug} resolves to an image`, img.status === 200 && (img.contentType || '').startsWith('image/'), JSON.stringify(img));
    results.cheatImage = img;
  }

  // no external CDN dependencies site-wide on tested surfaces
  const cdnHits = allResponses.filter(u => /unpkg\.com|scrollreveal|cdnjs\.cloudflare\.com/i.test(u));
  check('zero unpkg/scrollreveal CDN requests', cdnHits.length === 0, JSON.stringify(cdnHits));

  fs.writeFileSync(path.join(outDir, 'verify-results.json'), JSON.stringify(results, null, 2));
  await browser.close();
  const failed = results.checks.filter(c => !c.pass);
  console.log('TOTAL ' + results.checks.length + ' FAILED ' + failed.length);
  process.exit(failed.length ? 1 : 0);
})();
