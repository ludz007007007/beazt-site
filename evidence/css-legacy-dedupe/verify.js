// css-legacy-dedupe verification harness (2026-09-17)
// 1. Computed-style OLD (HEAD css via route interception) vs NEW (worktree css)
//    diff on identical rendered HTML — proves the dedupe changed nothing visually
//    except the two whitelisted intended changes.
// 2. Touch-target audit at 320px (VAL-HOME-010 / VAL-STORE-010 / VAL-PRODUCT-010 + qty stepper).
// 3. Console errors + horizontal overflow at 320/390/768/1440.
// 4. Alpine :class tab migration + hero alt + utility-class definitions.
const { chromium } = require('playwright');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:5000';
const OUT = __dirname;
const REPO = path.join(__dirname, '..', '..');
const oldCss = execSync('git show HEAD:static/css/style.css', { cwd: REPO, maxBuffer: 64 * 1024 * 1024 }).toString();

const results = { computedDiff: [], touchTargets: [], sweep: [], checks: [], screenshots: [] };
const expectedDiff = (r) =>
  (r.sel === '.legal-toc-link' && r.prop === 'background-color') ||
  (r.sel === '.nav-logo' && r.prop === 'min-height');

const DIFF_PAGES = [
  { name: 'home', path: '/' },
  { name: 'cheats', path: '/cheats' },
  { name: 'product', path: null },
  { name: 'login', path: '/auth/login' },
  { name: 'terms', path: '/terms' },
];
const SWEEP_PAGES = [
  { name: 'home', path: '/' },
  { name: 'cheats', path: '/cheats' },
  { name: 'product', path: null },
  { name: 'faq', path: '/faq' },
  { name: 'loader', path: '/loader' },
  { name: 'feedback', path: '/feedback' },
  { name: 'login', path: '/auth/login' },
  { name: 'terms', path: '/terms-of-service' },
];
const VIEWPORTS = [[320, 680], [390, 720], [768, 900], [1440, 900]];
const DIFF_SELECTORS = ['.card', '.badge', '.badge-primary', '.badge-success', '.badge-info',
  '.btn-discord', '.nav-logo', '.hero-main', '.hero-pill', '.hero-pill-dot', '.hero-stats',
  '.hero-stat', '.hero-stat-val', '.hero-stat-label', '.hero-bg-image', '.form-input', '.legal-toc-link'];
const PROPS = ['display', 'position', 'min-height', 'padding-top', 'margin-top', 'font-size', 'font-family',
  'font-weight', 'letter-spacing', 'text-transform', 'color', 'background-color', 'background-image',
  'border-top-color', 'border-radius', 'box-shadow', 'transition-property', 'opacity'];

async function openPage(browser, url, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
  if (opts.oldCss) {
    await ctx.route('**/style.css*', route => route.fulfill({ body: oldCss, contentType: 'text/css' }));
  }
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
  page.on('pageerror', e => consoleErrors.push('pageerror: ' + String(e).slice(0, 200)));
  await page.goto(url, { waitUntil: 'load', timeout: 45000 });
  await page.waitForTimeout(1800);
  return { ctx, page, consoleErrors };
}

async function snap(page, extraTag) {
  let base;
  try {
    base = await page.evaluate(({ sels, props }) => {
    const out = {};
    for (const sel of sels) {
      out[sel] = [];
      for (const el of Array.from(document.querySelectorAll(sel)).slice(0, 3)) {
        const cs = getComputedStyle(el);
        const rec = {};
        for (const p of props) rec[p] = cs.getPropertyValue(p);
        out[sel].push(rec);
      }
    }
    return out;
  }, { sels: DIFF_SELECTORS, props: PROPS });
  } catch (e) { return { __error: String(e).slice(0, 300) }; }
  if (extraTag) base.__tag = extraTag;
  return base;
}

(async () => {
  const browser = await chromium.launch();

  // discover a real product path
  {
    const { ctx, page } = await openPage(browser, BASE + '/cheats');
    let href = null;
    try { href = await page.$eval('a.cheat-card', a => a.getAttribute('href')); } catch (e) {}
    for (const p of [...DIFF_PAGES, ...SWEEP_PAGES]) if (p.path === null) p.path = href || '/__no-product__';
    results.productPath = href;
    await ctx.close();
  }

  // ---- computed-style old vs new diff (identical HTML, viewport 1440)
  for (const dp of DIFF_PAGES) {
    if (!dp.path || dp.path === '/__no-product__') continue;
    const url = dp.path.startsWith('http') ? dp.path : BASE + dp.path;
    const nw = await openPage(browser, url);
    if (dp.name === 'product') { await nw.page.waitForSelector('.pd-qty-btn', { state: 'visible', timeout: 15000 }).catch(() => {}); }
    const newSnap = await snap(nw.page, dp.name === 'home' ? 'hover:nav' : null);
    let hoverNew = null, focusNew = null;
    if (dp.name === 'home') {
      try { await nw.page.hover('.nav-links .btn-discord'); await nw.page.waitForTimeout(300); hoverNew = (await snap(nw.page))['.btn-discord'][0]; } catch (e) {}
    }
    if (dp.name === 'login') {
      try { await nw.page.focus('.form-input'); await nw.page.waitForTimeout(200); focusNew = (await snap(nw.page))['.form-input'][0]; } catch (e) {}
    }
    const od = await openPage(browser, url, { oldCss: true });
    if (dp.name === 'product') { await od.page.waitForSelector('.pd-qty-btn', { state: 'visible', timeout: 15000 }).catch(() => {}); }
    const oldSnap = await snap(od.page, null);
    let hoverOld = null, focusOld = null;
    if (dp.name === 'home') {
      try { await od.page.hover('.nav-links .btn-discord'); await od.page.waitForTimeout(300); hoverOld = (await snap(od.page))['.btn-discord'][0]; } catch (e) {}
    }
    if (dp.name === 'login') {
      try { await od.page.focus('.form-input'); await od.page.waitForTimeout(200); focusOld = (await snap(od.page))['.form-input'][0]; } catch (e) {}
    }
    if (newSnap && oldSnap && !newSnap.__error && !oldSnap.__error) {
      for (const sel of DIFF_SELECTORS) {
        const na = newSnap[sel] || [], oa = oldSnap[sel] || [];
        for (let i = 0; i < Math.max(na.length, oa.length); i++) {
          for (const p of PROPS) {
            const nv = (na[i] || {})[p], ov = (oa[i] || {})[p];
            if (nv !== ov) results.computedDiff.push({ page: dp.name, sel, idx: i, prop: p, old: ov, new: nv, expected: expectedDiff({ page: dp.name, sel, prop: p }) });
          }
        }
      }
    } else {
      results.computedDiff.push({ page: dp.name, error: 'snapshot failed', newErr: newSnap && newSnap.__error, oldErr: oldSnap && oldSnap.__error });
    }
    if (hoverNew && hoverOld) {
      for (const p of ['border-top-color', 'background-image', 'box-shadow', 'min-height', 'text-transform']) {
        if (hoverNew[p] !== hoverOld[p]) results.computedDiff.push({ page: 'home', sel: '.btn-discord:hover', prop: p, old: hoverOld[p], new: hoverNew[p], expected: false });
      }
    }
    if (focusNew && focusOld) {
      for (const p of PROPS) {
        if (focusNew[p] !== focusOld[p]) results.computedDiff.push({ page: 'login', sel: '.form-input:focus', prop: p, old: focusOld[p], new: focusNew[p], expected: false });
      }
    }
    await nw.ctx.close(); await od.ctx.close();
  }

  // ---- touch targets at 320px (new css)
  {
    const ctx = await browser.newContext({ viewport: { width: 320, height: 680 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    async function measure(url, sels, waitSel) {
      await page.goto(BASE + url, { waitUntil: 'load', timeout: 45000 });
      if (waitSel) await page.waitForSelector(waitSel, { state: 'visible', timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(800);
      return page.evaluate(sels => {
        return sels.map(sel => {
          const els = Array.from(document.querySelectorAll(sel));
          return els.map(el => {
            const r = el.getBoundingClientRect();
            return { sel, w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10, ok: r.width >= 43.5 && r.height >= 43.5 };
          });
        }).flat();
      }, sels);
    }
    results.touchTargets.push(...await measure('/', ['.nav-logo']));
    results.touchTargets.push(...await measure('/cheats', ['.nav-logo']));
    if (results.productPath) {
      results.touchTargets.push(...await measure(results.productPath, ['a.pd-back', '.pd-qty-btn', '.pd-qty-input'], '.pd-qty-btn'));
    }
    await ctx.close();
  }

  // ---- sweep: console errors + overflow at all viewports, screenshots at 320/1440
  for (const [w, h] of VIEWPORTS) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' });
    for (const sp of SWEEP_PAGES) {
      if (!sp.path || sp.path === '/__no-product__') continue;
      const page = await ctx.newPage();
      const errs = [];
      page.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 200)); });
      page.on('pageerror', e => errs.push('pageerror: ' + String(e).slice(0, 200)));
      await page.goto(BASE + sp.path, { waitUntil: 'load', timeout: 45000 });
      await page.waitForTimeout(1200);
      const overflow = await page.evaluate(() => ({
        scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth,
      }));
      results.sweep.push({ viewport: w + 'x' + h, page: sp.name, consoleErrors: errs, horizontalOverflow: overflow.scrollW > overflow.clientW + 1, scrollW: overflow.scrollW });
      if ((w === 320 || w === 1440) && ['home', 'cheats', 'product'].includes(sp.name)) {
        const file = path.join(OUT, `${sp.name}-${w}x${h}.png`);
        await page.screenshot({ path: file, fullPage: w === 320 });
        results.screenshots.push(file);
      }
      await page.close();
    }
    await ctx.close();
  }

  // ---- functional checks
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    // hero alt=""
    await page.goto(BASE + '/', { waitUntil: 'load' }); await page.waitForTimeout(800);
    const alt = await page.$eval('.hero-bg-image', img => img.getAttribute('alt')).catch(() => 'MISSING');
    results.checks.push({ name: 'hero-bg-image alt is empty', pass: alt === '', value: alt });
    // utilities defined
    await page.goto(BASE + '/cheats', { waitUntil: 'load' }); await page.waitForTimeout(800);
    const util = await page.evaluate(() => {
      const s = document.querySelector('.page-section'), h = document.querySelector('.page-header'), t1 = document.querySelector('.t-h1');
      return {
        pageSectionPadding: s ? getComputedStyle(s).paddingTop : 'MISSING',
        pageHeaderMargin: h ? getComputedStyle(h).marginBottom : 'MISSING',
        t1FontSize: t1 ? getComputedStyle(t1).fontSize : 'MISSING',
        t1FontFamily: t1 ? getComputedStyle(t1).fontFamily.slice(0, 40) : 'MISSING',
      };
    });
    results.checks.push({ name: 'page-section has padding', pass: util.pageSectionPadding !== '0px' && util.pageSectionPadding !== 'MISSING', value: util.pageSectionPadding });
    results.checks.push({ name: 'page-header has margin', pass: util.pageHeaderMargin !== '0px' && util.pageHeaderMargin !== 'MISSING', value: util.pageHeaderMargin });
    results.checks.push({ name: 't-h1 renders', pass: util.t1FontSize !== 'MISSING' && util.t1FontFamily.includes('Inter'), value: util.t1FontSize + ' / ' + util.t1FontFamily });
    // pd-heading + product tab migration + qty interaction
    if (results.productPath) {
      await page.goto(BASE + results.productPath, { waitUntil: 'load' });
      await page.waitForSelector('.pd-qty-btn', { state: 'visible', timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(600);
      const pd = await page.evaluate(() => {
        const el = document.querySelector('.pd-heading');
        return el ? { ff: getComputedStyle(el).fontFamily.slice(0, 40), fs: getComputedStyle(el).fontSize } : null;
      });
      results.checks.push({ name: 'pd-heading renders with display font', pass: !!pd && pd.ff.includes('Inter'), value: pd ? pd.ff + ' ' + pd.fs : 'MISSING' });
      await page.click('#tab-visualization');
      await page.waitForTimeout(300);
      const tab1 = await page.evaluate(() => ({
        visShown: !document.getElementById('panel-visualization').closest('[x-cloak]') && getComputedStyle(document.getElementById('panel-visualization')).display !== 'none',
        overviewHidden: document.getElementById('panel-overview').classList.contains('is-hidden'),
      }));
      results.checks.push({ name: 'tab switch via :class works (visualization)', pass: tab1.visShown && tab1.overviewHidden, value: JSON.stringify(tab1) });
      await page.click('#tab-buyer'); await page.waitForTimeout(300);
      const tab2 = await page.evaluate(() => ({
        buyerShown: getComputedStyle(document.getElementById('panel-buyer')).display !== 'none',
        visHidden: document.getElementById('panel-visualization').classList.contains('is-hidden'),
      }));
      results.checks.push({ name: 'tab switch via :class works (buyer)', pass: tab2.buyerShown && tab2.visHidden, value: JSON.stringify(tab2) });
      await page.click('#tab-overview'); await page.waitForTimeout(200);
      // qty stepper: click + and check input value
      const qty = await page.evaluate(() => {
        const input = document.querySelector('.pd-qty-input');
        const btns = document.querySelectorAll('.pd-qty-btn');
        btns[btns.length - 1].click();
        return new Promise(res => setTimeout(() => res({ value: input.value, h: Math.round(input.getBoundingClientRect().height) }), 300));
      });
      results.checks.push({ name: 'qty stepper works, input >=44px tall', pass: String(qty.value) === '2' && qty.h >= 43.5, value: JSON.stringify(qty) });
      // legal toc token (on /terms)
      // legal toc token (on /terms) — the background rule lives in a max-width
      // media query, so measure at a 320px viewport
      await page.setViewportSize({ width: 320, height: 680 });
      await page.goto(BASE + '/terms-of-service', { waitUntil: 'load' }); await page.waitForTimeout(600);
      const toc = await page.evaluate(() => {
        const el = document.querySelector('.legal-toc-link');
        return el ? getComputedStyle(el).backgroundColor : 'MISSING';
      });
      results.checks.push({ name: 'legal toc-link uses token (bg-elevated)', pass: toc === 'rgb(12, 22, 37)', value: toc });
    }
    await ctx.close();
  }

  fs.writeFileSync(path.join(OUT, 'verify-results.json'), JSON.stringify(results, null, 2));

  // summary
  const unexpected = results.computedDiff.filter(d => !d.expected);
  console.log('== computed diffs: ' + results.computedDiff.length + ' (unexpected: ' + unexpected.length + ')');
  for (const d of results.computedDiff) console.log((d.expected ? '[expected] ' : '[UNEXPECTED] ') + d.page + ' ' + (d.sel || '') + ' ' + (d.prop || '') + ': ' + JSON.stringify(d.old) + ' -> ' + JSON.stringify(d.new));
  console.log('== touch targets:');
  for (const t of results.touchTargets) console.log((t.ok ? 'PASS' : 'FAIL') + ' ' + t.sel + ' ' + t.w + 'x' + t.h);
  console.log('== checks:');
  for (const c of results.checks) console.log((c.pass ? 'PASS' : 'FAIL') + ' ' + c.name + ' = ' + c.value);
  const overflowPages = results.sweep.filter(s => s.horizontalOverflow);
  console.log('== overflow pages: ' + overflowPages.length);
  for (const o of overflowPages) console.log('OVERFLOW ' + o.viewport + ' ' + o.page + ' scrollW=' + o.scrollW);
  const errPages = results.sweep.filter(s => s.consoleErrors.length);
  console.log('== console errors: ' + errPages.length + ' page-viewport combos');
  for (const e of errPages) console.log('ERRORS ' + e.viewport + ' ' + e.page + ': ' + e.consoleErrors.join(' | '));
  await browser.close();
})();
