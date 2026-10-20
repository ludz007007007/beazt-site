/* VAL-HOME-007 verification: FAQ preview accordion (approved no-Python
   fallback — renders the Jinja-substituted section with the real style.css
   and script.js served from the repo root). */
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const OUT_DIR = path.join(ROOT, "evidence", "home", "faq-preview");
const PORT = 8791;

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

  await page.goto(`http://127.0.0.1:${PORT}/evidence/home/faq-preview/preview.html`, { waitUntil: "networkidle" });

  // Icons render (lucide replaces the data-lucide spans with SVGs that keep
  // the original classes, so the icon element itself becomes svg.icon)
  await page.waitForFunction(() => document.querySelectorAll("svg.icon").length >= 8, null, { timeout: 10000 });

  const items = page.locator(".faq-item");
  const count = await items.count();
  check("4 FAQ items rendered", count === 4, `count=${count}`);

  // Collapsed by default, with per-question icons
  for (let i = 0; i < count; i++) {
    const item = items.nth(i);
    const expanded = await item.locator(".faq-question").getAttribute("aria-expanded");
    const answerH = await item.locator(".faq-answer").evaluate((el) => el.clientHeight);
    check(`item ${i + 1} collapsed by default`, expanded === "false" && answerH < 2, `aria-expanded=${expanded} height=${answerH.toFixed(1)}`);
    const qIcon = await item.locator(".faq-question-text").evaluate((el) => (el.matches("svg") || el.querySelector("svg")) ? 1 : 0);
    check(`item ${i + 1} has question icon`, qIcon === 1);
  }

  // Answer text matches the FAQ page copy
  const expected = [
    "BEAZT runs as a read-only external stack. Launch the loader, paste your key, and start Rust — no injection or file edits.",
    "Keys hit your dashboard in under 15 seconds after payment. Track them anytime on the My Keys page.",
    "Stripe handles every card — Visa, Mastercard, Amex — with full encryption. We never see or store your card data.",
    "Maintenance time never burns your license. We pause timers and post live status threads in Discord.",
  ];
  for (let i = 0; i < count; i++) {
    const text = (await items.nth(i).locator(".faq-answer-inner p").first().innerText()).trim();
    check(`item ${i + 1} answer matches FAQ page copy`, text === expected[i], JSON.stringify(text.slice(0, 60)));
  }

  // Deep links point at the matching FAQ page anchors
  const expectedHrefs = ["/faq#faq-answer-1", "/faq#faq-answer-5", "/faq#faq-answer-4", "/faq#faq-answer-8"];
  for (let i = 0; i < count; i++) {
    const href = await items.nth(i).locator(".faq-answer-more a").getAttribute("href");
    check(`item ${i + 1} links to /faq anchor`, href === expectedHrefs[i], `href=${href}`);
  }
  const seeAll = await page.locator('a.btn-ghost[href="/faq"]').count();
  check("See all FAQs button links to /faq", seeAll === 1);

  // Smooth animation: transition declared on .faq-answer
  const transition = await page.locator(".faq-answer").first().evaluate((el) => getComputedStyle(el).transition);
  check("expand/collapse animated", /grid-template-rows/.test(transition) && /0\.[0-9]+s|0\.[0-9]+ms|[1-9]s/.test(transition), transition);

  await page.screenshot({ path: path.join(OUT_DIR, "desktop-1280-collapsed.png"), fullPage: true });

  // Accordion behavior: open each, verify, exclusive-open, close again
  for (let i = 0; i < count; i++) {
    const item = items.nth(i);
    await item.locator(".faq-question").click();
    await page.waitForTimeout(450); // let the grid-rows animation settle
    const expanded = await item.locator(".faq-question").getAttribute("aria-expanded");
    const open = await item.evaluate((el) => el.classList.contains("open"));
    const answerH = await item.locator(".faq-answer").evaluate((el) => el.clientHeight);
    check(`item ${i + 1} expands on click`, expanded === "true" && open && answerH > 40, `aria-expanded=${expanded} height=${answerH.toFixed(1)}`);
    const othersOpen = await page.locator(".faq-item.open").count();
    check(`item ${i + 1} open is exclusive`, othersOpen === 1, `open items=${othersOpen}`);
    if (i === 1) {
      await page.screenshot({ path: path.join(OUT_DIR, "desktop-1280-expanded.png"), fullPage: true });
    }
  }
  // Collapse again
  await items.nth(count - 1).locator(".faq-question").click();
  await page.waitForTimeout(450);
  const openAfter = await page.locator(".faq-item.open").count();
  check("all items collapse again", openAfter === 0, `open items=${openAfter}`);

  // Keyboard: focus + Enter toggles
  await items.nth(0).locator(".faq-question").focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(350);
  const kbOpen = await items.nth(0).locator(".faq-question").getAttribute("aria-expanded");
  check("keyboard Enter toggles accordion", kbOpen === "true");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(350);

  // Focus ring visibility
  await items.nth(0).locator(".faq-question").focus();
  const focusShadow = await items.nth(0).locator(".faq-question").evaluate((el) => getComputedStyle(el).boxShadow);
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

  // Touch target: question button >= 44px tall on mobile
  const btnH = await items.nth(0).locator(".faq-question").evaluate((el) => el.getBoundingClientRect().height);
  check("touch target >= 44px on mobile", btnH >= 44, `height=${btnH.toFixed(1)}`);

  await page.screenshot({ path: path.join(OUT_DIR, "mobile-390-expanded.png"), fullPage: true });

  check("zero console errors", consoleErrors.length === 0, consoleErrors.join(" | ").slice(0, 200));

  await browser.close();
  server.close();
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} checks passed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error("SCRIPT ERROR:", e); process.exit(2); });
