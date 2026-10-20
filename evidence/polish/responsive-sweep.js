// VAL-HOME-010, VAL-STORE-010, VAL-PRODUCT-010, VAL-CROSS-008
// Responsive sweep: horizontal scroll check, touch targets, hamburger, sticky panels.
const { chromium } = require('E:\\github\\rust beazt\\BEAZT-WEBSITE\\node_modules\\playwright');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:5000';
const OUT = path.join(__dirname, 'responsive-results.json');
const EVID = __dirname;

const PAGES = [
  { id: 'home', path: '/' },
  { id: 'cheats', path: '/cheats' },
  { id: 'product', path: '/product/rust-external-private' },
  { id: 'faq', path: '/faq' },
];
const VPS = [
  { w: 320, h: 680 }, { w: 390, h: 844 }, { w: 768, h: 1024 },
  { w: 1440, h: 900 }, { w: 1920, h: 1080 },
];

(async () => {
  const results = { pages: [], errors: [] };
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  page.on('pageerror', e => results.errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') results.errors.push('console: ' + m.text()); });

  for (const p of PAGES) {
    const rec = { id: p.id, path: p.path, viewports: {}, touchTargets320: null, hamburger: null, sticky: null, screenshots: [] };
    for (const vp of VPS) {
      await page.setViewportSize({ width: vp.w, height: vp.h });
      await page.goto(BASE + p.path, { waitUntil: 'networkidle', timeout: 30000 });
      await page.waitForTimeout(1200); // Alpine/Lucide hydration
      const m = await page.evaluate(() => {
        const d = document.documentElement;
        return {
          scrollWidth: d.scrollWidth,
          bodyScrollWidth: document.body ? document.body.scrollWidth : null,
          innerWidth: window.innerWidth,
        };
      });
      m.horizontalOverflow = m.scrollWidth > m.innerWidth + 1 || (m.bodyScrollWidth != null && m.bodyScrollWidth > m.innerWidth + 1);
      rec.viewports[vp.w] = m;

      // Screenshot at 320 and 1440
      if (vp.w === 320 || vp.w === 1440) {
        const file = `${p.id}-${vp.w}x${vp.h}.png`;
        await page.screenshot({ path: path.join(EVID, file), fullPage: false });
        rec.screenshots.push(file);
      }
    }

    // Touch target audit at 320px
    await page.setViewportSize({ width: 320, height: 680 });
    await page.goto(BASE + p.path, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(1200);
    rec.touchTargets320 = await page.evaluate(() => {
      const els = Array.from(document.querySelectorAll('a[href], button, input, select, textarea, [role="button"]'));
      const out = [];
      for (const el of els) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.pointerEvents === 'none') continue;
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) continue;
        if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
        // clip to viewport for offscreen partials
        const h = Math.min(r.height, innerHeight - Math.max(0, r.top));
        const w = Math.min(r.width, innerWidth - Math.max(0, r.left));
        if (w < 44 || h < 44) {
          out.push({
            tag: el.tagName.toLowerCase(),
            cls: (el.className && typeof el.className === 'string') ? el.className.split(' ').slice(0, 3).join('.') : '',
            text: (el.textContent || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 40),
            w: Math.round(w * 10) / 10, h: Math.round(h * 10) / 10,
          });
        }
      }
      return { small: out, count: out.length };
    });

    // Hamburger test at 320px
    const burger = await page.$('button.nav-burger');
    if (burger) {
      const hb = { present: true, visible: false, ariaExpandedBefore: null, opened: false, ariaExpandedAfter: null, overlayVisible: false, linkNavigated: null, closedAfterNav: null };
      hb.visible = await burger.isVisible() && await burger.evaluate(el => getComputedStyle(el).display !== 'none');
      hb.ariaExpandedBefore = await burger.getAttribute('aria-expanded');
      const menu = await page.$('#mobile-menu');
      await burger.click();
      await page.waitForTimeout(500);
      hb.ariaExpandedAfter = await burger.getAttribute('aria-expanded');
      hb.opened = menu ? await menu.evaluate(el => el.classList.contains('is-open') && getComputedStyle(el).visibility === 'visible') : false;
      const overlay = await page.$('.mobile-menu-overlay');
      hb.overlayVisible = overlay ? await overlay.evaluate(el => el.classList.contains('is-visible')) : false;
      const file = `${p.id}-320-hamburger-open.png`;
      await page.screenshot({ path: path.join(EVID, file) });
      rec.screenshots.push(file);
      // Click first menu link
      const link = await page.$('#mobile-menu a[href]');
      if (link) {
        const href = await link.getAttribute('href');
        await link.click();
        await page.waitForTimeout(1500);
        hb.linkNavigated = page.url();
        const burgerAfter = await page.$('button.nav-burger');
        const menuAfter = await page.$('#mobile-menu');
        hb.closedAfterNav = menuAfter && burgerAfter
          ? await menuAfter.evaluate(el => !el.classList.contains('is-open'))
          : null;
      }
      rec.hamburger = hb;
      // back to page for sticky test
      await page.goto(BASE + p.path, { waitUntil: 'networkidle', timeout: 30000 });
      await page.waitForTimeout(800);
    } else {
      rec.hamburger = { present: false, visible: false };
    }

    // Sticky purchase panel (desktop) / mobile buy bar (product only)
    if (p.id === 'product') {
      // desktop 1440
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(BASE + p.path, { waitUntil: 'networkidle', timeout: 30000 });
      await page.waitForTimeout(1200);
      const panel = await page.$('.purchase-panel');
      const panelVis = panel ? await panel.isVisible() : false;
      await page.mouse.wheel(0, 1200); await page.waitForTimeout(600);
      await page.mouse.wheel(0, 1200); await page.waitForTimeout(600);
      const panelAfterScroll = panel ? await panel.evaluate(el => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return { inViewport: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth, position: cs.position, top: cs.top };
      }) : null;
      const fileD = 'product-1440-purchase-panel-scrolled.png';
      await page.screenshot({ path: path.join(EVID, fileD) });
      rec.screenshots.push(fileD);
      // mobile 320
      await page.setViewportSize({ width: 320, height: 680 });
      await page.goto(BASE + p.path, { waitUntil: 'networkidle', timeout: 30000 });
      await page.waitForTimeout(1200);
      const bar = await page.$('.mobile-buy-bar');
      const barInfo = bar ? await bar.evaluate(el => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return {
          display: cs.display, position: cs.position,
          visible: cs.display !== 'none' && r.height > 0,
          pinnedBottom: Math.abs(innerHeight - r.bottom) < 60 && r.top < innerHeight,
          rect: { top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height) },
        };
      }) : null;
      const fileM = 'product-320-mobile-buy-bar.png';
      await page.screenshot({ path: path.join(EVID, fileM) });
      rec.screenshots.push(fileM);
      rec.sticky = { desktop: { present: !!panel, visible: panelVis, afterScroll: panelAfterScroll }, mobile: barInfo };
    }
    results.pages.push(rec);
  }

  fs.writeFileSync(OUT, JSON.stringify(results, null, 2));
  console.log('DONE');
  console.log(JSON.stringify(results, null, 1));
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
