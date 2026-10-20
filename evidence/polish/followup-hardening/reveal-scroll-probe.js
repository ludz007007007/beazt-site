// store-followup-hardening: prove all homepage .reveal elements reveal on scroll
// in a normal default-motion browser (dependency-free scroll reveal, VAL-PERF-001).
const { chromium } = require('E:\\github\\rust beazt\\BEAZT-WEBSITE\\node_modules\\playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const outDir = __dirname;
  const browser = await chromium.launch();
  const page = await browser.newPage(); // NO reducedMotion override
  await page.goto('http://127.0.0.1:5000/', { waitUntil: 'networkidle' });
  const before = await page.evaluate(() => ({
    total: document.querySelectorAll('.reveal').length,
    visible: document.querySelectorAll('.reveal.visible').length
  }));
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.waitForTimeout(1500);
  const after = await page.evaluate(() => ({
    total: document.querySelectorAll('.reveal').length,
    visible: document.querySelectorAll('.reveal.visible').length
  }));
  const pass = after.total > 0 && after.visible === after.total;
  const result = { check: 'homepage .reveal elements all reveal on scroll (default motion)', before, after, pass };
  console.log(JSON.stringify(result));
  fs.writeFileSync(path.join(outDir, 'reveal-scroll-results.json'), JSON.stringify(result, null, 2));
  await browser.close();
  process.exit(pass ? 0 : 1);
})();
