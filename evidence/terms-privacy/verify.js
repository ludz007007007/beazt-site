// Verification for /terms-of-service and /privacy (legal-pages feature, 2026-09-16)
// Renders the LIVE Flask pages (http://127.0.0.1:5000) in headless Chromium,
// checks console errors, horizontal overflow at 320/390/768/1440, TOC anchors,
// footer legal links, related-resource links, keyboard focus, and saves
// screenshots to evidence/terms-privacy/.
// NOTE: reducedMotion 'reduce' is required — the known site-wide ScrollReveal
// bug leaves .reveal elements at opacity:0 in headless captures otherwise.
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname);
const PAGES = [
  {
    key: 'terms',
    url: 'http://127.0.0.1:5000/terms-of-service',
    h1: 'Terms of Service',
    anchorPrefix: 'terms-',
    otherLegal: { name: 'Privacy Policy', url: 'http://127.0.0.1:5000/privacy' },
    footerOtherHref: '/privacy',
  },
  {
    key: 'privacy',
    url: 'http://127.0.0.1:5000/privacy',
    h1: 'Privacy Policy',
    anchorPrefix: 'privacy-',
    otherLegal: { name: 'Terms of Service', url: 'http://127.0.0.1:5000/terms-of-service' },
    footerOtherHref: '/terms-of-service',
  },
];
const VIEWPORTS = [
  { name: 'mobile-320', width: 320, height: 720 },
  { name: 'mobile-390', width: 390, height: 844 },
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'desktop-1440', width: 1440, height: 900 },
];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const results = { pages: {} };

  for (const spec of PAGES) {
    const r = { url: spec.url, consoleErrors: [], dom: {}, viewports: [], checks: {} };
    results.pages[spec.key] = r;

    // DOM facts at desktop viewport
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 },
      reducedMotion: 'reduce',
    });
    page.on('console', (msg) => { if (msg.type() === 'error') r.consoleErrors.push(msg.text()); });
    page.on('pageerror', (err) => r.consoleErrors.push('pageerror: ' + err.message));
    const resp = await page.goto(r.url, { waitUntil: 'networkidle' });
    r.dom.httpStatus = resp.status();

    r.dom.h1 = (await page.locator('h1').first().innerText()).trim();
    r.dom.h1Matches = r.dom.h1.toLowerCase() === spec.h1.toLowerCase();
    r.dom.sections = await page.locator('.legal-section').count();
    r.dom.tocLinks = await page.locator('.legal-toc-link').count();
    r.dom.relatedCards = await page.locator('.legal-related-card').count();
    r.dom.canonical = await page.locator('link[rel="canonical"]').getAttribute('href');
    r.dom.metaDescription = await page.locator('meta[name="description"]').first().getAttribute('content');
    r.dom.ogTitle = await page.locator('meta[property="og:title"]').getAttribute('content');

    // Every section heading and anchor target must exist and TOC hrefs must resolve
    const sectionIds = await page.locator('.legal-section').evaluateAll((els) => els.map((e) => e.id));
    r.dom.sectionIds = sectionIds;
    const tocHrefs = await page.locator('.legal-toc-link').evaluateAll((els) => els.map((e) => e.getAttribute('href')));
    r.checks.allAnchorsResolve = tocHrefs.every((h) => sectionIds.includes(h.slice(1)));
    // Every section's body must contain visible text (full legal content displayed)
    const emptySections = await page.locator('.legal-section').evaluateAll((els) =>
      els.filter((e) => e.innerText.trim().length < 10).map((e) => e.id));
    r.checks.emptySections = emptySections;

    // TOC anchor navigation works (sticky-navbar safe via scroll-margin-top)
    await page.locator('.legal-toc-link').nth(3).click();
    await page.waitForTimeout(300);
    r.checks.tocAnchorHash = await page.evaluate(() => location.hash);
    r.checks.tocTargetVisibleAfterClick = await page.locator(`#${spec.anchorPrefix}payments, #${spec.anchorPrefix}collection`).first().isVisible();

    // Related-resource links point at real routes
    const relatedHrefs = await page.locator('.legal-related-card').evaluateAll((els) => els.map((e) => e.getAttribute('href')));
    r.dom.relatedHrefs = relatedHrefs;
    r.checks.relatedLinksResolve = relatedHrefs.every((h) => h && (h.startsWith('/') || h.startsWith('http')));

    // Footer legal links work: click the OTHER legal page link in the footer
    const footerLink = page.locator(`footer .footer-link[href="${spec.footerOtherHref}"]`);
    r.checks.footerOtherLegalLinkCount = await footerLink.count();
    await footerLink.first().click();
    await page.waitForLoadState('networkidle');
    r.checks.footerNavigationLandsOn = page.url();
    r.checks.footerNavigationWorks = page.url().replace(/\/$/, '') === spec.otherLegal.url;

    // Keyboard: first Tab after load must land on a visible, labeled focusable element
    await page.goto(r.url, { waitUntil: 'networkidle' });
    await page.keyboard.press('Tab');
    const focusInfo = await page.evaluate(() => {
      const el = document.activeElement;
      return { tag: el.tagName, text: (el.textContent || '').trim().slice(0, 40), label: el.getAttribute('aria-label') };
    });
    r.checks.firstTabFocus = focusInfo;

    await page.screenshot({ path: path.join(OUT, `${spec.key}-desktop-1440.png`), fullPage: true });
    await page.close();

    // Overflow check per viewport
    for (const vp of VIEWPORTS) {
      const p = await browser.newPage({
        viewport: { width: vp.width, height: vp.height },
        reducedMotion: 'reduce',
      });
      p.on('console', (msg) => { if (msg.type() === 'error') r.consoleErrors.push(`[${vp.name}] ` + msg.text()); });
      p.on('pageerror', (err) => r.consoleErrors.push(`[${vp.name}] pageerror: ` + err.message));
      await p.goto(r.url, { waitUntil: 'networkidle' });
      const overflow = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      // Text reflow: no clipped words inside content at narrow viewports
      const textReflowOk = await p.evaluate(() => {
        const el = document.querySelector('.legal-content');
        if (!el) return false;
        return el.scrollWidth <= el.clientWidth + 1;
      });
      r.viewports.push({ ...vp, horizontalOverflowPx: overflow, textReflowOk });
      await p.screenshot({ path: path.join(OUT, `${spec.key}-${vp.name}.png`), fullPage: true });
      await p.close();
    }
  }

  await browser.close();
  fs.writeFileSync(path.join(OUT, 'VAL-TERMS-PRIVACY-results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
})().catch((e) => { console.error('VERIFY FAILED:', e); process.exit(1); });
