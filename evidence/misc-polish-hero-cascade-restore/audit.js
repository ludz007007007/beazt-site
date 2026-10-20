// Extended old-vs-HEAD computed-style audit (misc-polish-hero-cascade-restore)
// Baseline "old"  = pre-regression CSS (commit dd0ebe2 = a42afb9^), where the deleted
//                   legacy hero block was the cascade winner. Served via route interception.
// "HEAD"          = working-tree CSS served by live Flask on http://localhost:5000.
// Coverage gotcha (library/perf-notes.md): measure the FULL effective declaration set
// (all computed properties, incl. shorthand longhands and :hover states), not a shortlist.
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const BASE_CSS = fs.readFileSync(path.join(__dirname, 'old-style.css'), 'utf8');
const URL_BASE = 'http://localhost:5000';

// selector -> states to measure
const TARGETS = {
  '/': [
    ['.hero-stats', ['normal']],
    ['.hero-stat', ['normal', 'hover']],
    ['.nav-logo', ['normal', 'hover']],
    ['.bento-card', ['normal', 'hover']],
    ['.stat-bar-item', ['normal', 'hover']],
    ['.btn-discord', ['normal', 'hover']],
    ['.btn-ghost', ['normal', 'hover']],
    ['.btn-lg', ['normal', 'hover']],
    ['.section-eyebrow', ['normal']],
    ['.nav-cta', ['normal', 'hover']],
    ['.faq-question', ['normal', 'hover']],
    ['.nav-status', ['normal']],
  ],
  '/faq': [
    ['.form-input', ['normal', 'hover', 'focus']],
    ['.faq-item', ['normal']],
  ],
  '/product/rust-external-private': [
    ['.pd-back', ['normal', 'hover']],
    ['[class*="badge"]', ['normal', 'hover']],
    ['.form-input', ['normal']],
  ],
  '/cheats': [
    ['.cheat-card', ['normal', 'hover']],
    ['[class*="badge"]', ['normal']],
    ['.btn-discord', ['normal', 'hover']],
  ],
};

async function snapshot(page, sel, state) {
  const handle = await page.$(sel);
  if (!handle) return null;
  await handle.scrollIntoViewIfNeeded();
  if (state === 'hover') {
    await handle.hover();
    await page.waitForTimeout(700); // let transitions settle (duration-normal 250ms)
  } else if (state === 'focus') {
    await handle.focus();
    await page.waitForTimeout(700);
  } else {
    // move mouse away so no stray hover state applies
    await page.mouse.move(2, 2);
    await page.waitForTimeout(250);
  }
  return handle.evaluate((el) => {
    const cs = getComputedStyle(el);
    const o = {};
    for (const p of cs) o[p] = cs.getPropertyValue(p);
    return o;
  });
}

function diffStyles(a, b) {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  const d = {};
  for (const k of keys) {
    if (a[k] !== b[k]) d[k] = { old: a[k], new: b[k] };
  }
  return d;
}

(async () => {
  const browser = await chromium.launch();
  const results = { expectedDiffs: [], unexpectedDiffs: [], assertions: [], consoleErrors: [], overflow: [], notes: [] };

  // ---- Pass 1: HEAD, explicit assertions of the 5 restored values + baseline sanity ----
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
    await page.goto(URL_BASE + '/', { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(500);

    const norm = (s) => (s || '').replace(/\s+/g, '');
    const assertVal = async (sel, state, prop, expected, label) => {
      const s = await snapshot(page, sel, state);
      const got = s ? s[prop] : null;
      const ok = s && norm(got) === norm(expected);
      results.assertions.push({ label, sel, state, prop, expected, got, ok: !!ok });
      return s;
    };
    const stat = await assertVal('.hero-stats', 'normal', 'max-width', '700px', 'hero-stats max-width 700px');
    const st = await assertVal('.hero-stat', 'normal', 'padding-left', '20px', 'hero-stat padding-left 20px');
    await assertVal('.hero-stat', 'normal', 'padding-right', '20px', 'hero-stat padding-right 20px');
    const hov = await assertVal('.hero-stat', 'hover', 'border-top-color', 'rgba(22,139,255,0.2)', 'hero-stat:hover border-color --border-accent-subtle');
    await assertVal('.hero-stat', 'hover', 'transform', 'matrix(1, 0, 0, 1, 0, -2)', 'hero-stat:hover translateY(-2px)');
    const shadow = hov ? hov['box-shadow'] : null;
    results.assertions.push({
      label: 'hero-stat:hover box-shadow uses --glow-accent-subtle (0 0 15px rgba(22,139,255,0.15))',
      got: shadow, ok: !!shadow && norm(shadow).includes('rgba(22,139,255,0.15)0px0px15px'),
    });
    // HEAD must keep the intentional a42afb9 44px touch targets (previously verified)
    const nl = await snapshot(page, '.nav-logo', 'normal');
    results.assertions.push({ label: 'nav-logo min-height 44px (a42afb9 touch target, previously verified)', got: nl && nl['min-height'], ok: !!nl && nl['min-height'] === '44px' });
    // baseline sanity: old CSS must render the same legacy winners
    const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await ctx2.route('**/static/css/style.css*', (route) => route.fulfill({ body: BASE_CSS, contentType: 'text/css' }));
    const page2 = await ctx2.newPage();
    await page2.goto(URL_BASE + '/', { waitUntil: 'networkidle' });
    await page2.evaluate(() => document.fonts.ready);
    await page2.waitForTimeout(500);
    const b1 = await snapshot(page2, '.hero-stats', 'normal');
    const b2 = await snapshot(page2, '.hero-stat', 'normal');
    const b3 = await snapshot(page2, '.hero-stat', 'hover');
    results.assertions.push({ label: 'BASELINE sanity: .hero-stats max-width 700px', got: b1 && b1['max-width'], ok: b1 && b1['max-width'] === '700px' });
    results.assertions.push({ label: 'BASELINE sanity: .hero-stat padding-left 20px', got: b2 && b2['padding-left'], ok: b2 && b2['padding-left'] === '20px' });
    results.assertions.push({ label: 'BASELINE sanity: .hero-stat:hover border-color subtle', got: b3 && b3['border-top-color'], ok: b3 && norm(b3['border-top-color']) === 'rgba(22,139,255,0.2)' });
    results.assertions.push({ label: 'BASELINE sanity: .hero-stat:hover translateY -2', got: b3 && b3['transform'], ok: b3 && b3['transform'] === 'matrix(1, 0, 0, 1, 0, -2)' });
    results.assertions.push({ label: 'BASELINE sanity: .hero-stat:hover box-shadow subtle glow', got: b3 && b3['box-shadow'], ok: b3 && norm(b3['box-shadow']).includes('rgba(22,139,255,0.15)0px0px15px') });
    await ctx2.close();
    await ctx.close();
  }

  // ---- Pass 2: full computed-style diff, old vs HEAD, per page/target/state ----
  for (const [pageKey, targets] of Object.entries(TARGETS)) {
    let url = URL_BASE + pageKey;
    const mkCtx = async (baseline) => {
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      if (baseline) await ctx.route('**/static/css/style.css*', (route) => route.fulfill({ body: BASE_CSS, contentType: 'text/css' }));
      const page = await ctx.newPage();
      return { ctx, page };
    };
    const { ctx: ctxO, page: po } = await mkCtx(true);
    const { ctx: ctxN, page: pn } = await mkCtx(false);

    for (const p of [po, pn]) {
      await p.goto(url, { waitUntil: 'networkidle' });
      await p.evaluate(() => document.fonts.ready);
      await p.waitForTimeout(600);
    }
    for (const [sel, states] of targets) {
      for (const state of states) {
        const o = await snapshot(po, sel, state);
        const n = await snapshot(pn, sel, state);
        if (!o || !n) { results.notes.push('missing on ' + pageKey + ': ' + sel + ' (' + state + ')'); continue; }
        const d = diffStyles(o, n);
        if (Object.keys(d).length) {
          // Whitelist: a42afb9 intentionally raised .nav-logo to a 44px touch target
          // (previously verified surface expects 44px at HEAD; baseline pre-a42afb9 was 40px).
          const isNavLogo44 = sel === '.nav-logo' &&
            Object.keys(d).every((k) => ['min-height', 'min-width', 'min-block-size', 'min-inline-size', 'height', 'block-size', 'perspective-origin', 'transform-origin'].includes(k)) &&
            Object.values(d).every((v) => v.new.includes('44px') || /(\d+)px$/.test(v.new));
          if (isNavLogo44) {
            results.expectedDiffs.push({ page: pageKey, url, selector: sel, state, diffs: d, reason: 'intentional a42afb9 44px touch target (previously verified)' });
          } else {
            results.unexpectedDiffs.push({ page: pageKey, url, selector: sel, state, diffs: d });
          }
        }
      }
    }
    await ctxO.close();
    await ctxN.close();
  }

  // ---- Pass 3: console errors + horizontal overflow at 320/390/768/1440 (HEAD) ----
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
    for (const w of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width: w, height: 900 });
      await page.goto(URL_BASE + '/', { waitUntil: 'networkidle' });
      await page.waitForTimeout(800);
      const sw = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      }));
      results.overflow.push({ width: w, ...sw, overflow: sw.scrollWidth > sw.innerWidth + 1 });
    }
    results.consoleErrors = errors;
    await ctx.close();
  }

  await browser.close();
  fs.writeFileSync(path.join(__dirname, 'audit-results.json'), JSON.stringify(results, null, 2));

  const failed = results.assertions.filter((a) => !a.ok);
  console.log('=== ASSERTIONS ===');
  for (const a of results.assertions) console.log((a.ok ? 'PASS ' : 'FAIL ') + a.label + '  (got: ' + a.got + ')');
  console.log('=== UNEXPECTED DIFFS: ' + results.unexpectedDiffs.length + ' ===');
  for (const u of results.unexpectedDiffs) {
    console.log('-- ' + u.page + ' ' + u.selector + ' [' + u.state + ']');
    for (const [k, v] of Object.entries(u.diffs)) console.log('   ' + k + ': ' + JSON.stringify(v.old) + ' -> ' + JSON.stringify(v.new));
  }
  console.log('=== EXPECTED (whitelisted) DIFFS: ' + results.expectedDiffs.length + ' ===');
  for (const u of results.expectedDiffs) console.log('-- ' + u.page + ' ' + u.selector + ' [' + u.state + '] ' + u.reason);
  console.log('=== CONSOLE ERRORS: ' + results.consoleErrors.length + ' ===');
  results.consoleErrors.forEach((e) => console.log('   ' + e));
  console.log('=== OVERFLOW ===');
  for (const o of results.overflow) console.log((o.overflow ? 'FAIL ' : 'PASS ') + o.width + 'px scrollWidth=' + o.scrollWidth);
  console.log('NOTES: ' + JSON.stringify(results.notes));
  const ok = failed.length === 0 && results.unexpectedDiffs.length === 0 && results.consoleErrors.length === 0 && results.overflow.every((o) => !o.overflow);
  console.log(ok ? 'AUDIT OK' : 'AUDIT FAILED');
  process.exit(ok ? 0 : 1);
})();
