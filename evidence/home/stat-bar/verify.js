/* Playwright verification for the homepage stat bar (VAL-HOME-006).
 * Loads evidence/home/stat-bar/preview.html (template markup + real style.css)
 * at four viewports, captures screenshots, and reports console errors,
 * horizontal overflow, grid/gradient computed styles, and stat text values.
 */
const { chromium } = require("playwright");
const path = require("path");

const VIEWPORTS = [
  { name: "desktop-1440", width: 1440, height: 900 },
  { name: "tablet-768", width: 768, height: 1024 },
  { name: "mobile-390", width: 390, height: 844 },
  { name: "mobile-320", width: 320, height: 680 },
];

(async () => {
  const previewUrl = "file:///" + path.resolve(__dirname, "preview.html").replace(/\\/g, "/");
  const browser = await chromium.launch();
  const report = { previewUrl, viewports: {} };

  for (const vp of VIEWPORTS) {
    const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
    const consoleErrors = [];
    page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });
    page.on("pageerror", (err) => consoleErrors.push("pageerror: " + err.message));

    await page.goto(previewUrl, { waitUntil: "networkidle", timeout: 30000 }).catch((e) => {
      consoleErrors.push("goto: " + e.message);
    });
    await page.waitForTimeout(400);

    const facts = await page.evaluate(() => {
      const bar = document.querySelector(".stat-bar");
      const inner = document.querySelector(".stat-bar-inner");
      const barStyle = bar ? getComputedStyle(bar) : null;
      const num = document.querySelector(".stat-bar-num");
      const nums = [...document.querySelectorAll(".stat-bar-num")].map((n) => n.textContent.trim());
      const labels = [...document.querySelectorAll(".stat-bar-label")].map((l) => l.textContent.trim());
      const heroVals = [...document.querySelectorAll(".hero-stat-val")].map((v) => v.textContent.trim());
      return {
        statBarPresent: !!bar,
        gradientBackground: barStyle ? barStyle.backgroundImage.slice(0, 90) : null,
        borderTopBottom: barStyle ? [barStyle.borderTopWidth, barStyle.borderBottomWidth].join("/") : null,
        gridColumnsDesktop: inner ? getComputedStyle(inner).gridTemplateColumns.split(" ").length : 0,
        statNumFontSizePx: num ? parseFloat(getComputedStyle(num).fontSize) : null,
        statValues: nums,
        statLabels: labels,
        heroStatValues: heroVals,
        ariaLabel: bar ? bar.getAttribute("aria-label") : null,
        horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      };
    });

    await page.screenshot({ path: path.join(__dirname, `${vp.name}.png`), fullPage: true });
    report.viewports[vp.name] = { ...facts, consoleErrors };
    await page.close();
  }

  await browser.close();
  console.log(JSON.stringify(report, null, 2));
})().catch((err) => { console.error(err); process.exit(1); });
