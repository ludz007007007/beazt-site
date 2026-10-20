const { chromium } = require('E:\\github\\rust beazt\\BEAZT-WEBSITE\\node_modules\\playwright');
const fs = require('fs');

function sessionFromJar(path) {
  const lines = fs.readFileSync(path, 'utf8').split(/\r?\n/);
  for (const line of lines) {
    if (!line.trim()) continue;
    const clean = line.replace(/^#HttpOnly_/, '');
    if (line.startsWith('#') && clean === line) continue;
    const parts = clean.split(/\t/);
    if (parts.length >= 7 && parts[5] === 'session') return parts[6];
  }
  return null;
}

(async () => {
  const sess = sessionFromJar('evidence\\polish\\admin-unnest-form\\jar2.txt');
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  await ctx.addCookies([{ name: 'session', value: sess, domain: 'localhost', path: '/' }]);
  const page = await ctx.newPage();

  const posts = [];
  page.on('request', req => {
    if (req.method() === 'POST') {
      posts.push({ url: req.url(), postData: req.postData() });
    }
  });

  await page.goto('http://localhost:5000/admin/settings', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);

  const probe = await page.evaluate(() => {
    const btn = document.querySelector('button[form="chairfbi-test-form"]');
    const testForm = document.getElementById('chairfbi-test-form');
    const outerForm = document.querySelector('form[enctype="multipart/form-data"]');
    const fd = new FormData(testForm);
    const entries = {};
    for (const [k, v] of fd.entries()) entries[k] = v.length > 20 ? '<64hex-or-long>' : v;
    return {
      btnFormOwner: btn.form ? btn.form.id : null,
      btnInOuterForm: !!btn.closest('form'),
      btnClosestFormEnctype: btn.closest('form') ? btn.closest('form').getAttribute('enctype') : null,
      testFormEntries: entries,
      outerFormFirstFields: Array.from(outerForm.elements).slice(0, 5).map(e => e.name || e.tagName),
    };
  });
  console.log('PROBE:', JSON.stringify(probe, null, 2));

  await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle' }),
    page.evaluate(() => document.querySelector('button[form="chairfbi-test-form"]').click()),
  ]);
  console.log('POSTS_AFTER_CLICK:', JSON.stringify(posts, null, 2));
  console.log('FINAL_URL:', page.url());
  await browser.close();
})().catch(e => { console.error('FAIL:', e); process.exit(1); });
