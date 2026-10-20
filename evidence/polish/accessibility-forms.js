// VAL-ACCESS-003/004 retry with correct auth URLs (/auth/login, /auth/signup)
const { chromium } = require('E:\\github\\rust beazt\\BEAZT-WEBSITE\\node_modules\\playwright');
const fs = require('fs');
const path = require('path');
const OUT = path.join(__dirname, 'accessibility-forms-results.json');
const BASE = 'http://127.0.0.1:5000';

(async () => {
  const results = {};
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  results.forms = {};
  for (const t of [{ id: 'login', path: '/auth/login' }, { id: 'signup', path: '/auth/signup' }]) {
    const resp = await page.goto(BASE + t.path, { waitUntil: 'networkidle', timeout: 30000 }).then(r => r.status()).catch(() => null);
    await page.waitForTimeout(1000);
    const audit = await page.evaluate(() => {
      const fields = Array.from(document.querySelectorAll('form input:not([type=hidden]), form select, form textarea'));
      return fields.map(f => {
        const id = f.id;
        const labelFor = id ? document.querySelector(`label[for="${id}"]`) : null;
        const wrapped = f.closest('label');
        const label = labelFor || wrapped;
        return {
          field: f.tagName.toLowerCase() + (id ? '#' + id : '') + '[type=' + (f.type || '?') + ']',
          hasLabel: !!label,
          labelText: label ? label.textContent.trim().slice(0, 30) : null,
          ariaLabel: f.getAttribute('aria-label'),
          ariaLabelledBy: f.getAttribute('aria-labelledby'),
          autocomplete: f.getAttribute('autocomplete'),
        };
      });
    });
    results.forms[t.id] = { url: BASE + t.path, status: resp, fields: audit, allLabeled: audit.every(f => f.hasLabel || f.ariaLabel || f.ariaLabelledBy) };
    await page.screenshot({ path: path.join(__dirname, `access-003-${t.id}.png`) });
  }

  // VAL-ACCESS-004: empty submit on /auth/login (client-side validation only; form has novalidate)
  await page.goto(BASE + '/auth/login', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(1000);
  const val = { url: BASE + '/auth/login', attempted: true, errorShown: null, wired: null, noNavigation: null, posted: false };
  page.on('request', r => { if (r.method() === 'POST') val.posted = r.url(); });
  const submitBtn = await page.$('#login-form button[type=submit], #login-form [type=submit]');
  if (submitBtn) {
    await submitBtn.click();
    await page.waitForTimeout(1200);
    val.noNavigation = page.url() === BASE + '/auth/login';
    val.urlAfter = page.url();
    const st = await page.evaluate(() => {
      const out = [];
      for (const input of document.querySelectorAll('#login-form input')) {
        const desc = input.getAttribute('aria-describedby');
        const errId = input.getAttribute('data-error-id') || (desc || '').split(' ').find(x => x.includes('error'));
        const errEl = errId ? document.getElementById(errId) : null;
        out.push({
          input: input.id,
          ariaDescribedBy: desc,
          errId,
          errExists: !!errEl,
          errHidden: errEl ? errEl.hidden : null,
          errText: errEl ? errEl.textContent.trim().slice(0, 80) : null,
          errRole: errEl ? errEl.getAttribute('role') : null,
          errVisible: errEl ? errEl.getBoundingClientRect().height > 0 && !errEl.hidden : false,
        });
      }
      return out;
    });
    val.errors = st;
    const anyShown = st.find(e => e.errVisible && e.errText);
    val.errorShown = !!anyShown;
    if (anyShown) {
      val.wired = !!(anyShown.errId && anyShown.ariaDescribedBy && anyShown.ariaDescribedBy.includes(anyShown.errId) && anyShown.errRole === 'alert');
    }
    await page.screenshot({ path: path.join(__dirname, 'access-004-login-validation-error.png') });
  }
  results.validation = val;
  results.consoleErrors = errors;
  fs.writeFileSync(OUT, JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 1));
  console.log('DONE');
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
