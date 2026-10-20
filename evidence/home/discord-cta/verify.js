/* VAL-HOME-008 verification: Discord CTA section (approved no-Python
   fallback — renders the Jinja-substituted section with the real style.css
   and script.js served from the repo root). */
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const OUT_DIR = path.join(ROOT, "evidence", "home", "discord-cta");
const PORT = 8793;
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

(async () => {
  const server = await serve();
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  await page.goto(`http://127.0.0.1:${PORT}/evidence/home/discord-cta/preview.html`, { waitUntil: "networkidle" });

  const section = page.locator(".discord-cta-section");
  const btn = page.locator(".btn-discord--lg");
  await section.waitFor({ state: "visible", timeout: 10000 });

  // Discord-branded background: section base + ::before glow uses Discord blurple (88,101,242)
  const bg = await section.evaluate((el) => getComputedStyle(el).backgroundColor);
  const glow = await section.evaluate((el) => getComputedStyle(el, "::before").backgroundImage);
  check("section has dark deep background", bg === "rgb(8, 16, 28)" || /rgb\(5, 7, 11\)|rgb\(8, 16, 28\)/.test(bg), bg);
  check("ambient glow uses Discord blurple", glow.includes("88, 101, 242"), glow.slice(0, 80));

  // Top border shine also Discord-branded
  const topShine = await section.evaluate((el) => getComputedStyle(el, "::after").backgroundImage);
  check("top border shine Discord-branded", topShine.includes("88, 101, 242"), topShine.slice(0, 80));

  // Heading + eyebrow
  const eyebrow = (await section.locator(".section-eyebrow").innerText()).trim();
  check("eyebrow shows Community", eyebrow.toLowerCase() === "community", eyebrow);
  const h2 = (await section.locator("h2").innerText()).trim();
  check("heading is Join the BEAZT Discord", h2 === "Join the BEAZT Discord", h2);

  // Button: Discord icon + label + link behavior
  const btnText = (await btn.innerText()).trim();
  check("button label is Join Our Discord Server", btnText.toLowerCase() === "join our discord server", JSON.stringify(btnText));
  const href = await btn.getAttribute("href");
  check("button links to configured Discord URL", href === DISCORD_URL, `href=${href}`);
  const target = await btn.getAttribute("target");
  const rel = await btn.getAttribute("rel") || "";
  check("opens Discord in new tab", target === "_blank" && rel.includes("noopener") && rel.includes("noreferrer"), `target=${target} rel=${rel}`);

  // Discord brand mark: inline SVG (fill currentColor, official path) — not a generic chat bubble
  const iconInfo = await btn.evaluate((el) => {
    const svg = el.querySelector("svg.icon");
    if (!svg) return null;
    const p = svg.querySelector("path");
    return { fill: svg.getAttribute("fill"), d: p ? p.getAttribute("d") : null, text: el.textContent };
  });
  check("button shows Discord icon", !!iconInfo && iconInfo.fill === "currentColor" && iconInfo.d.startsWith("M20.317"), iconInfo ? `fill=${iconInfo.fill} d=${iconInfo.d.slice(0, 12)}…` : "no svg.icon");
  const btnColor = await btn.evaluate((el) => getComputedStyle(el).color);
  check("button background is Discord blurple gradient", /88, 101, 242/.test(await btn.evaluate((el) => getComputedStyle(el).backgroundImage)), btnColor);

  // Metadata row
  const meta = section.locator(".discord-cta-meta");
  const metaItems = await meta.locator("span").allInnerTexts();
  const joined = metaItems.join(" | ");
  check("Operators Online indicator", /Operators Online/.test(joined), joined);
  check("24/7 Support metadata", /24\/7 Support/.test(joined), joined);
  check("Instant Replies metadata", /Instant Replies/.test(joined), joined);
  const dotAnim = await meta.locator(".dot").evaluate((el) => {
    const s = getComputedStyle(el);
    return { name: s.animationName, bg: s.backgroundColor };
  });
  check("online dot pulses green", dotAnim.name === "pulse" && /rgb\((?:[1-9]?\d|1\d\d|2[0-4]\d|25[0-5]),/.test(dotAnim.bg), JSON.stringify(dotAnim));

  await page.screenshot({ path: path.join(OUT_DIR, "desktop-1280.png"), fullPage: true });

  // Premium hover effect: transform + glow shadow change on hover
  const before = await btn.evaluate((el) => ({ shadow: getComputedStyle(el).boxShadow, transform: getComputedStyle(el).transform }));
  await btn.hover();
  await page.waitForTimeout(650); // shine sweep + transitions settle
  const after = await btn.evaluate((el) => ({ shadow: getComputedStyle(el).boxShadow, transform: getComputedStyle(el).transform }));
  check("hover changes transform", before.transform !== after.transform, `${before.transform} -> ${after.transform}`);
  check("hover adds glow shadow", before.shadow !== after.shadow && /88, 101, 242/.test(after.shadow), after.shadow.slice(0, 80));
  await page.screenshot({ path: path.join(OUT_DIR, "desktop-1280-hover.png"), fullPage: true });

  // Keyboard: focusable, focus ring visible
  await page.mouse.move(5, 5);
  await btn.focus();
  const focusShadow = await btn.evaluate((el) => getComputedStyle(el).boxShadow);
  check("focus state visible", focusShadow && focusShadow !== "none", focusShadow.slice(0, 60));

  // Viewport sweep: no horizontal overflow at 320/390/768/1280
  for (const w of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width: w, height: 900 });
    await page.waitForTimeout(150);
    const overflow = await page.evaluate(() => ({
      sw: document.scrollingElement.scrollWidth, cw: document.scrollingElement.clientWidth,
    }));
    check(`no horizontal overflow @${w}px`, overflow.sw <= overflow.cw, `scrollWidth=${overflow.sw} clientWidth=${overflow.cw}`);
  }

  // Touch target: button >= 44px tall on mobile
  await page.setViewportSize({ width: 390, height: 900 });
  await page.waitForTimeout(150);
  const btnH = await btn.evaluate((el) => el.getBoundingClientRect().height);
  check("touch target >= 44px on mobile", btnH >= 44, `height=${btnH.toFixed(1)}`);

  await page.screenshot({ path: path.join(OUT_DIR, "mobile-390.png"), fullPage: true });

  check("zero console errors", consoleErrors.length === 0, consoleErrors.join(" | ").slice(0, 200));

  await browser.close();
  server.close();
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} checks passed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error("SCRIPT ERROR:", e); process.exit(2); });
