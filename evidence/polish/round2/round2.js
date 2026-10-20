// Round-2 polish validation harness (VAL-HOME-010, VAL-STORE-010, VAL-PRODUCT-010, VAL-CROSS-008)
// Read-only live checks against http://127.0.0.1:5000 — no form submissions, no DB writes.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:5000';
const OUT = __dirname;
const PAGES = [
  { name: 'home', path: '/' },
  { name: 'cheats', path: '/cheats' },
  { name: 'product', path: '/product/rust-external-private' },
  { name: 'faq', path: '/faq' },
];
const SWEEP = [320, 390, 768, 1440, 1920];
const results = { generatedAt: new Date().toISOString(), base: BASE, touchTargets: {}, overflow: {}, stickyPanel: null, mobileBuyBar: null, hamburger: {}, consoleErrors: {} };

function isFailure(err) {
  const m = (err.text && err.text()) || String(err);
  if (/favicon/i.test(m)) return false;
  if (/Failed to load resource.*40[34]/.test(m) && /favicon/i.test(m)) return false;
  return true;
}

(async () => {
  const browser = await chromium.launch({ headless: true });

  // ---------- Part 1: touch targets + hamburger + buy bar + overflow at 320 ----------
  for (const pg of PAGES) {
    const ctx = await browser.newContext({ viewport: { width: 320, height: 680 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', (msg) => { if (msg.type() === 'error' && isFailure(msg)) errors.push(msg.text()); });
    page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));

    await page.goto(BASE + pg.path, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => page.goto(BASE + pg.path, { waitUntil: 'load', timeout: 30000 }));
    await page.waitForTimeout(1200); // Alpine/Lucide hydration

    // touch targets present at 320px
    const targets = pg.name === 'product'
      ? ['.nav-logo', 'a.pd-back', '.nav-burger', '.pd-qty-btn', '.pd-qty-input']
      : ['.nav-logo', '.nav-burger'];
    const measured = {};
    for (const sel of targets) {
      const el = page.locator(sel).first();
      if ((await el.count()) === 0) { measured[sel] = { found: false }; continue; }
      const box = await el.boundingBox();
      const vis = await el.isVisible();
      measured[sel] = { found: true, visible: vis, width: box ? Math.round(box.width * 10) / 10 : null, height: box ? Math.round(box.height * 10) / 10 : null };
    }
    results.touchTargets[pg.name] = measured;

    // overflow at current 320 viewport
    const ovf = await page.evaluate(() => {
      const de = document.documentElement, b = document.body;
      return {
        htmlScrollW: de.scrollWidth, htmlClientW: de.clientWidth,
        bodyScrollW: b.scrollWidth, bodyClientW: b.clientWidth,
      };
    });
    results.overflow[pg.name] = results.overflow[pg.name] || {};
    results.overflow[pg.name][320] = { ...ovf, overflow: ovf.htmlScrollW > ovf.htmlClientW + 1 };

    await page.screenshot({ path: path.join(OUT, `${pg.name}-320.png`), fullPage: false });

    // product-only: mobile buy bar at 320
    if (pg.name === 'product') {
      const buyBar = await page.evaluate(() => {
        const el = document.querySelector('.mobile-buy-bar');
        if (!el) return { found: false };
        const cs = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return {
          found: true, display: cs.display, position: cs.position,
          top: Math.round(r.top), bottom: Math.round(r.bottom), width: Math.round(r.width), height: Math.round(r.height),
          atViewportBottom: Math.abs(r.bottom - window.innerHeight) <= 2,
          visible: cs.display !== 'none' && r.height > 0,
        };
      });
      results.mobileBuyBar = buyBar;
      await page.screenshot({ path: path.join(OUT, 'product-320-buybar.png'), fullPage: false });
    }

    // hamburger flow: visible -> open -> screenshot -> close via toggle -> reopen -> click first link
    const burger = page.locator('.nav-burger');
    const burgerVis = await burger.isVisible();
    const burgerBox = await burger.boundingBox();
    let flow = { burgerVisible: burgerVis, burgerBox };
    if (burgerVis) {
      await burger.click();
      await page.waitForTimeout(500);
      flow.openState = await page.evaluate(() => {
        const menu = document.querySelector('.mobile-menu');
        if (!menu) return { menuFound: false };
        const cs = getComputedStyle(menu);
        return { menuFound: true, isOpen: menu.classList.contains('is-open'), visibility: cs.visibility, opacity: cs.opacity, pointerEvents: cs.pointerEvents };
      });
      await page.screenshot({ path: path.join(OUT, `${pg.name}-320-menu-open.png`), fullPage: false });

      // close via overlay tap (overlay z-index sits above the navbar burger)
      const overlay = page.locator('.mobile-menu-overlay.is-visible');
      if ((await overlay.count()) > 0) {
        await overlay.click({ position: { x: 10, y: 36 } }); // exposed strip above menu (menu top:72px)
        await page.waitForTimeout(500);
      }
      flow.closeState = await page.evaluate(() => {
        const menu = document.querySelector('.mobile-menu');
        return menu ? { isOpen: menu.classList.contains('is-open'), visibility: getComputedStyle(menu).visibility } : { menuFound: false };
      });

      // reopen and click first link
      await burger.click();
      await page.waitForTimeout(500);
      const firstLink = page.locator('.mobile-menu.is-open a.nav-link').first();
      if ((await firstLink.count()) > 0) {
        const href = await firstLink.getAttribute('href');
        flow.clickedHref = href;
        const [nav] = await Promise.all([
          page.waitForNavigation({ waitUntil: 'load', timeout: 15000 }).catch(() => null),
          firstLink.click(),
        ]);
        await page.waitForTimeout(600);
        flow.afterNavUrl = page.url();
        flow.navigated = flow.afterNavUrl === new URL(href, BASE).href;
        flow.menuClosedAfterNav = await page.evaluate(() => {
          const menu = document.querySelector('.mobile-menu');
          return menu ? !menu.classList.contains('is-open') : true;
        });
      } else {
        flow.clickedHref = null;
      }
    }
    results.hamburger[pg.name] = flow;
    results.consoleErrors[pg.name] = errors;
    await ctx.close();
  }

  // ---------- Part 2: overflow sweep remaining widths ----------
  for (const pg of PAGES) {
    for (const w of SWEEP.filter((x) => x !== 320)) {
      const ctx = await browser.newContext({ viewport: { width: w, height: Math.min(Math.max(w, 680), 1000) } });
      const page = await ctx.newPage();
      await page.goto(BASE + pg.path, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => page.goto(BASE + pg.path, { waitUntil: 'load', timeout: 30000 }));
      await page.waitForTimeout(800);
      const ovf = await page.evaluate(() => {
        const de = document.documentElement, b = document.body;
        return { htmlScrollW: de.scrollWidth, htmlClientW: de.clientWidth, bodyScrollW: b.scrollWidth, bodyClientW: b.clientWidth };
      });
      results.overflow[pg.name][w] = { ...ovf, overflow: ovf.htmlScrollW > ovf.htmlClientW + 1 };
      if (w === 1920) await page.screenshot({ path: path.join(OUT, `${pg.name}-1920.png`), fullPage: false });
      await ctx.close();
    }
  }

  // ---------- Part 3: sticky purchase panel at 1440x900 ----------
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    await page.goto(BASE + '/product/rust-external-private', { waitUntil: 'networkidle', timeout: 30000 }).catch(() => page.goto(BASE + '/product/rust-external-private', { waitUntil: 'load', timeout: 30000 }));
    await page.waitForTimeout(1200);
    const before = await page.evaluate(() => {
      const el = document.querySelector('aside.purchase-panel');
      if (!el) return { found: false };
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return { found: true, position: cs.position, top: Math.round(r.top) };
    });
    await page.mouse.wheel(0, 800);
    await page.waitForTimeout(800);
    const after = await page.evaluate(() => {
      const el = document.querySelector('aside.purchase-panel');
      if (!el) return { found: false };
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return { found: true, position: cs.position, top: Math.round(r.top), scrollY: Math.round(window.scrollY), inViewport: r.top >= 0 && r.bottom <= window.innerHeight + 2 };
    });
    results.stickyPanel = { viewport: '1440x900', beforeScroll: before, afterScroll: after };
    await page.screenshot({ path: path.join(OUT, 'product-1440-scrolled-sticky.png'), fullPage: false });
    await ctx.close();
  }

  fs.writeFileSync(path.join(OUT, 'round2-results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
  await browser.close();
})().catch((e) => { console.error('HARNESS-ERROR', e); process.exit(1); });
