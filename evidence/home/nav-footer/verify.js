/* VAL-HOME-009 verification: global navigation + footer (page-navigation-and-footer).
   Approved no-Python fallback: serves the repo root locally and renders the
   Jinja-substituted preview with the real style.css and script.js. */
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const OUT_DIR = path.join(ROOT, "evidence", "home", "nav-footer");
const PORT = 8795;
const DISCORD_URL = "https://discord.gg/bU4tFA43KK"; // config.py DISCORD_PUBLIC_URL default

const MIME = {
  ".html": "text/html", ".css": "text/css", ".js": "text/javascript",
  ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml",
  ".woff2": "font/woff2", ".ico": "image/x-icon",
};

function serve() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const urlPath = decodeURIComponent(req.url.split("?")[0]);
      let fp = path.join(ROOT, urlPath === "/" ? "index.html" : urlPath);
      if (!fp.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
      fs.readFile(fp, (err, data) => {
        if (err) { res.writeHead(404); return res.end("not found"); }
        res.writeHead(200, { "Content-Type": MIME[path.extname(fp)] || "application/octet-stream" });
        res.end(data);
      });
    });
    server.listen(PORT, "127.0.0.1", () => resolve(server));
  });
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok, detail: detail || "" });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? " — " + detail : ""}`);
}
const firstDelay = (v) => parseFloat(String(v).split(",")[0]) || 0;

(async () => {
  const server = await serve();
  const browser = await chromium.launch();

  /* ─────────────────────────── DESKTOP 1440x900 ─────────────────────────── */
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => {
    if (!/Failed to load resource/.test(String(e))) consoleErrors.push(String(e));
  });

  await page.goto(`http://127.0.0.1:${PORT}/evidence/home/nav-footer/preview.html`, { waitUntil: "load" });
  await page.waitForTimeout(600);

  // Header: transparent at top, and at the very top of the page (canvas must
  // not take layout space above it)
  const topBg = await page.locator(".navbar").evaluate((el) => getComputedStyle(el).backgroundColor);
  const topBorder = await page.locator(".navbar").evaluate((el) => getComputedStyle(el).borderBottomColor);
  check("header transparent at top", topBg === "rgba(0, 0, 0, 0)", topBg);
  check("header border transparent at top", topBorder === "rgba(0, 0, 0, 0)", topBorder);
  const navNaturalTop = await page.locator(".navbar").evaluate((el) => el.getBoundingClientRect().top);
  check("header starts at top of page (no layout-space canvas)", Math.abs(navNaturalTop) < 1, `top=${navNaturalTop}`);
  await page.screenshot({ path: path.join(OUT_DIR, "desktop-1440-top.png") });

  // Sticky + scrolled state: dark blur backdrop, hairline blue bottom border
  await page.evaluate(() => window.scrollTo(0, 800));
  await page.waitForTimeout(400);
  const navTop = await page.locator(".navbar").evaluate((el) => el.getBoundingClientRect().top);
  check("header is sticky (top=0 after scroll)", Math.abs(navTop) < 1, `top=${navTop}`);
  const hasScrolled = await page.locator(".navbar.scrolled").count();
  check("scrolled class applied after scroll", hasScrolled === 1, `count=${hasScrolled}`);
  const scrolledBg = await page.locator(".navbar").evaluate((el) => getComputedStyle(el).backgroundColor);
  check("scrolled header uses dark translucent bg", scrolledBg === "rgba(5, 7, 11, 0.85)", scrolledBg);
  const blur = await page.locator(".navbar").evaluate((el) => getComputedStyle(el).backdropFilter + "/" + getComputedStyle(el).webkitBackdropFilter);
  check("scrolled header has backdrop blur", /blur/.test(blur), blur);
  const hairline = await page.locator(".navbar").evaluate((el) => getComputedStyle(el, "::after").backgroundImage);
  check("hairline bottom border is blue accent", hairline.includes("22, 139, 255"), hairline.slice(0, 90));
  await page.screenshot({ path: path.join(OUT_DIR, "desktop-1440-scrolled.png") });

  // Online indicator
  const statusVisible = await page.locator(".nav-status").isVisible();
  const statusText = (await page.locator(".nav-status").innerText()).trim().toLowerCase();
  check("online indicator visible in navbar", statusVisible && statusText === "systems online", `"${statusText}" visible=${statusVisible}`);

  // Desktop nav links
  const navChecks = [
    ["Home", "/"], ["Store", "/cheats"], ["Proof", "/feedback"],
    ["FAQ", "/faq"], ["Loader", "/loader"], ["Login", "/auth/login"],
  ];
  for (const [label, href] of navChecks) {
    const link = page.locator(`.nav-links .nav-link:text-is("${label}")`);
    const cnt = await link.count();
    const actual = cnt ? await link.getAttribute("href") : "(missing)";
    check(`desktop nav link ${label} -> ${href}`, cnt === 1 && actual === href, actual);
  }
  const discordBtn = page.locator(".nav-links .btn-discord");
  check("desktop Discord link correct + new tab",
    (await discordBtn.getAttribute("href")) === DISCORD_URL &&
    (await discordBtn.getAttribute("target")) === "_blank" &&
    ((await discordBtn.getAttribute("rel")) || "").includes("noopener"),
    await discordBtn.getAttribute("href"));
  const cta = page.locator(".nav-links .nav-cta");
  check("primary CTA is Sign Up -> /auth/signup",
    (await cta.innerText()).trim().toLowerCase() === "sign up" && (await cta.getAttribute("href")) === "/auth/signup",
    `${(await cta.innerText()).trim()} -> ${await cta.getAttribute("href")}`);
  const activeLink = (await page.locator(".nav-links .nav-link.active").innerText()).trim();
  check("active endpoint highlighted", activeLink === "Home", activeLink);

  // Keyboard: skip link is first tab stop
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.keyboard.press("Tab");
  const firstFocus = await page.evaluate(() => document.activeElement.className);
  check("skip link is first tab stop", /skip-link/.test(firstFocus), firstFocus);

  /* ─────────────────────────── FOOTER ─────────────────────────── */
  await page.locator(".footer").scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  const tagline = (await page.locator(".footer-tagline").innerText()).trim();
  check("footer tagline is Premium Gaming Enhancement", tagline === "Premium Gaming Enhancement", tagline);
  const footerLogo = await page.locator(".footer-logo img").count();
  check("footer shows BEAZT logo", footerLogo === 1, `count=${footerLogo}`);
  const groupLabels = (await page.locator(".footer-nav-label").allInnerTexts()).map((t) => t.trim().toLowerCase());
  check("footer has Legal/Support/Community groups",
    JSON.stringify(groupLabels) === JSON.stringify(["legal", "support", "community"]),
    JSON.stringify(groupLabels));
  const footerChecks = [
    ["Terms of Service", "/terms"], ["Privacy Policy", "/privacy"],
    ["FAQ", "/faq"], ["Reviews", "/feedback"], ["Setup Guide", "/loader"],
  ];
  for (const [label, href] of footerChecks) {
    const link = page.locator(`.footer .footer-link:text-is("${label}")`);
    const cnt = await link.count();
    const actual = cnt ? await link.getAttribute("href") : "(missing)";
    check(`footer link ${label} -> ${href}`, cnt === 1 && actual === href, actual);
  }
  const footerDiscord = page.locator(".footer .footer-link-discord");
  check("footer Discord link correct + new tab",
    (await footerDiscord.getAttribute("href")) === DISCORD_URL &&
    (await footerDiscord.getAttribute("target")) === "_blank",
    await footerDiscord.getAttribute("href"));
  const footerGlow = await page.locator(".footer-glow").evaluate((el) => getComputedStyle(el).backgroundImage);
  check("footer has subtle blue glow", footerGlow.includes("22, 139, 255") && footerGlow.includes("radial-gradient"), footerGlow.slice(0, 90));
  const footerShine = await page.locator(".footer").evaluate((el) => getComputedStyle(el, "::before").backgroundImage);
  check("footer top border shine is blue", footerShine.includes("22, 139, 255"), footerShine.slice(0, 90));
  await page.screenshot({ path: path.join(OUT_DIR, "desktop-1440-footer.png") });

  check("no console errors (desktop)", consoleErrors.length === 0, JSON.stringify(consoleErrors));
  await page.close();

  /* ─────────────────────────── MOBILE 390x844 ─────────────────────────── */
  const mConsoleErrors = [];
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true });
  mobile.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) mConsoleErrors.push(m.text());
  });
  mobile.on("pageerror", (e) => {
    if (!/Failed to load resource/.test(String(e))) mConsoleErrors.push(String(e));
  });

  await mobile.goto(`http://127.0.0.1:${PORT}/evidence/home/nav-footer/preview.html`, { waitUntil: "load" });
  await mobile.waitForTimeout(600);

  // Mobile layout primitives
  const navLinksHidden = await mobile.locator(".nav-links").evaluate((el) => getComputedStyle(el).display === "none");
  check("desktop nav links hidden on mobile", navLinksHidden);
  const burgerVisible = await mobile.locator(".nav-burger").isVisible();
  const burgerBox = await mobile.locator(".nav-burger").evaluate((el) => {
    const r = el.getBoundingClientRect(); return { w: r.width, h: r.height };
  });
  check("hamburger visible and 44px touch target", burgerVisible && burgerBox.w >= 44 && burgerBox.h >= 44, JSON.stringify(burgerBox));
  const statusDotVisible = await mobile.locator(".nav-status").isVisible();
  const statusLabelHidden = await mobile.locator(".nav-status-label").evaluate((el) => getComputedStyle(el).display === "none");
  check("online indicator compact (dot) on mobile", statusDotVisible && statusLabelHidden);
  const footerTagMobile = await mobile.locator(".footer-tagline").evaluate((el) => getComputedStyle(el).display);
  check("footer tagline visible on mobile", footerTagMobile !== "none", footerTagMobile);

  await mobile.screenshot({ path: path.join(OUT_DIR, "mobile-390-top.png") });

  // Open the menu
  await mobile.locator(".nav-burger").click();
  await mobile.waitForTimeout(500);
  const menuOpen = await mobile.locator(".mobile-menu.is-open").count();
  const overlayVisible = await mobile.locator(".mobile-menu-overlay.is-visible").count();
  const ariaOpen = await mobile.locator(".nav-burger").getAttribute("aria-expanded");
  check("mobile menu opens", menuOpen === 1 && overlayVisible === 1, `menu=${menuOpen} overlay=${overlayVisible}`);
  check("burger aria-expanded=true when open", ariaOpen === "true", ariaOpen);
  const bodyOverflow = await mobile.evaluate(() => document.body.style.overflow);
  check("body scroll locked while menu open", bodyOverflow === "hidden", bodyOverflow);

  // Staggered item animation: increasing transition delays, items end visible
  const delays = await mobile.evaluate(() => {
    const items = document.querySelectorAll(".mobile-menu.is-open .nav-link");
    return Array.from(items).slice(0, 5).map((el) => parseFloat(getComputedStyle(el).transitionDelay.split(",")[0]) || 0);
  });
  const staggered = delays.length >= 5 && delays[4] > delays[2] && delays[2] > delays[0] && delays[0] >= 0;
  check("menu items have staggered animation delays", staggered, JSON.stringify(delays));
  const itemState = await mobile.evaluate(() => {
    const el = document.querySelectorAll(".mobile-menu.is-open .nav-link")[2];
    const cs = getComputedStyle(el);
    return { opacity: cs.opacity, transform: cs.transform };
  });
  check("menu items settle visible", itemState.opacity === "1" && (itemState.transform === "none" || itemState.transform === "matrix(1, 0, 0, 1, 0, 0)"), JSON.stringify(itemState));
  await mobile.screenshot({ path: path.join(OUT_DIR, "mobile-390-menu-open.png") });

  // Overlay click closes (click below the menu panel so the overlay receives it)
  await mobile.locator(".mobile-menu-overlay").click({ position: { x: 195, y: 810 } });
  await mobile.waitForTimeout(450);
  const closedByOverlay = await mobile.locator(".mobile-menu.is-open").count();
  check("overlay click closes menu", closedByOverlay === 0);

  // Escape closes
  await mobile.locator(".nav-burger").click();
  await mobile.waitForTimeout(350);
  await mobile.keyboard.press("Escape");
  await mobile.waitForTimeout(450);
  const closedByEscape = await mobile.locator(".mobile-menu.is-open").count();
  check("Escape key closes menu", closedByEscape === 0);

  // Link click closes menu (navigation target 404s on the static server; class check happens immediately)
  await mobile.locator(".nav-burger").click();
  await mobile.waitForTimeout(350);
  const menuHrefs = await mobile.evaluate(() => Array.from(document.querySelectorAll(".mobile-menu .nav-link")).map((a) => a.getAttribute("href")));
  check("mobile menu has all sections (Home/Store/Proof/FAQ/Loader/Login/Sign Up)",
    JSON.stringify(menuHrefs) === JSON.stringify(["/", "/cheats", "/feedback", "/faq", "/loader", "/auth/login", "/auth/signup"]),
    JSON.stringify(menuHrefs));
  await mobile.locator('.mobile-menu .nav-link[href="/faq"]').click();
  await mobile.waitForTimeout(150);
  const closedByLink = await mobile.locator(".mobile-menu.is-open").count();
  check("menu closes on link click", closedByLink === 0);

  // No horizontal scroll
  await mobile.goto(`http://127.0.0.1:${PORT}/evidence/home/nav-footer/preview.html`, { waitUntil: "load" });
  await mobile.waitForTimeout(500);
  for (const width of [320, 390]) {
    await mobile.setViewportSize({ width, height: 844 });
    await mobile.waitForTimeout(250);
    const scrollW = await mobile.evaluate(() => document.scrollingElement.scrollWidth);
    check(`no horizontal scroll at ${width}px`, scrollW <= width, `scrollWidth=${scrollW}`);
    if (width === 320) await mobile.screenshot({ path: path.join(OUT_DIR, "mobile-320.png") });
  }
  check("no console errors (mobile)", mConsoleErrors.length === 0, JSON.stringify(mConsoleErrors));
  await mobile.close();

  await browser.close();
  server.close();

  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} checks passed`);
  fs.writeFileSync(path.join(OUT_DIR, "VAL-HOME-009.json"), JSON.stringify({
    assertion: "VAL-HOME-009 + footer expectedBehavior (page-navigation-and-footer)",
    passed, total: results.length, results,
  }, null, 2));
  process.exit(passed === results.length ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(1); });
