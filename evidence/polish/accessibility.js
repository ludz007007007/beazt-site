// VAL-ACCESS-001: skip link on / — VAL-ACCESS-002: keyboard nav + focus rings on /cheats, /faq
// VAL-ACCESS-003: form labels on /login, /register — VAL-ACCESS-004: validation error aria wiring
const { chromium } = require('E:\\github\\rust beazt\\BEAZT-WEBSITE\\node_modules\\playwright');
const fs = require('fs');
const path = require('path');
const OUT = path.join(__dirname, 'accessibility-results.json');
const BASE = 'http://127.0.0.1:5000';

(async () => {
  const results = {};
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  const focusInfo = () => page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return { focused: null, focusVisible: false, boxShadow: null, text: null };
    const cs = getComputedStyle(el);
    return {
      focused: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + String(el.className).split(' ').slice(0, 2).join('.'),
      focusVisible: el.matches(':focus-visible'),
      boxShadow: cs.boxShadow,
      text: (el.textContent || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 40),
      visibleRect: (() => { const r = el.getBoundingClientRect(); return { top: Math.round(r.top), left: Math.round(r.left), w: Math.round(r.width), h: Math.round(r.height) }; })(),
    };
  });

  // ---- VAL-ACCESS-001: skip link on /
  await page.goto(BASE + '/', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(1200);
  const skip = { present: false, hiddenBeforeFocus: null, focusedOnTab: false, focusVisible: false, visibleWhenFocused: false, activates: false, mainContentId: null };
  const skipEl = await page.$('.skip-link');
  if (skipEl) {
    skip.present = true;
    skip.mainContentId = !!(await page.$('#main-content'));
    skip.hiddenBeforeFocus = await skipEl.evaluate(el => { const r = el.getBoundingClientRect(); return r.bottom <= 0; });
    await page.keyboard.press('Tab');
    await page.waitForTimeout(200);
    const fi = await focusInfo();
    skip.focusedOnTab = fi.focused !== null && fi.focused.includes('skip-link');
    skip.focusVisible = fi.focusVisible;
    skip.visibleWhenFocused = fi.visibleRect ? fi.visibleRect.top >= 0 && fi.visibleRect.h > 0 : false;
    await page.screenshot({ path: path.join(__dirname, 'access-001-skip-link-focused.png') });
    await page.keyboard.press('Enter');
    await page.waitForTimeout(800);
    const after = await page.evaluate(() => {
      const el = document.activeElement;
      return {
        url: location.href,
        hash: location.hash,
        focused: el ? el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') : null,
        scrolledY: Math.round(scrollY),
        mainTop: Math.round(document.getElementById('main-content').getBoundingClientRect().top),
      };
    });
    skip.activates = after.hash === '#main-content' && after.mainTop >= -50;
    skip.afterActivate = after;
  }
  results.skipLink = skip;

  // ---- VAL-ACCESS-002: keyboard walk on /cheats and /faq
  results.keyboardWalk = {};
  for (const t of [{ id: 'cheats', path: '/cheats' }, { id: 'faq', path: '/faq' }]) {
    await page.goto(BASE + t.path, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(1200);
    const walk = { tabStops: [], focusRingGaps: [], firstFocusIsSkipLink: null };
    for (let i = 0; i < 15; i++) {
      await page.keyboard.press('Tab');
      await page.waitForTimeout(120);
      const fi = await focusInfo();
      if (fi.focused === null) break;
      walk.tabStops.push({ i: i + 1, ...fi });
      if (fi.focused.includes('skip-link')) { if (walk.firstFocusIsSkipLink === null) walk.firstFocusIsSkipLink = (i === 0); continue; }
      const hasRing = fi.focusVisible && fi.boxShadow && fi.boxShadow !== 'none' && fi.boxShadow.includes('168, 139, 255');
      if (!hasRing) walk.focusRingGaps.push({ i: i + 1, ...fi });
      await page.screenshot({ path: path.join(__dirname, `access-002-${t.id}-tab${i + 1}.png`) }).catch(() => {});
    }
    walk.nTabStops = walk.tabStops.length;
    results.keyboardWalk[t.id] = walk;
  }

  // FAQ accordion keyboard check on /faq
  await page.goto(BASE + '/faq', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(1200);
  const faq = { buttonCount: 0, keyboardOperable: null, ariaExpandedToggled: null, panelVisibleAfter: null };
  const faqBtns = await page.$$('details summary, .faq-question, .faq-toggle, button[aria-expanded]');
  faq.buttonCount = faqBtns.length;
  if (faqBtns.length) {
    const btn = faqBtns[0];
    await btn.focus();
    const before = await btn.evaluate(el => ({ expanded: el.getAttribute('aria-expanded'), tag: el.tagName }));
    await page.keyboard.press('Enter');
    await page.waitForTimeout(500);
    const after = await btn.evaluate(el => {
      const expanded = el.getAttribute('aria-expanded');
      let panel = expanded !== null ? document.getElementById(el.getAttribute('aria-controls')) : null;
      if (!panel && el.parentElement) panel = el.parentElement.querySelector('.faq-answer, .accordion-body, p, div:not(:first-child)');
      const vis = panel ? getComputedStyle(panel).display !== 'none' && panel.getBoundingClientRect().height > 0 : null;
      return { expanded, panelVisible: vis };
    });
    faq.keyboardOperable = true;
    faq.ariaExpandedToggled = before.expanded !== after.expanded;
    faq.panelVisibleAfter = after.panelVisible;
    faq.beforeAfter = { before, after };
    await page.screenshot({ path: path.join(__dirname, 'access-002-faq-accordion-open.png') });
  }
  results.faqAccordion = faq;

  // ---- VAL-ACCESS-003: labels on /login and /register
  results.forms = {};
  for (const t of [{ id: 'login', path: '/login' }, { id: 'register', path: '/register' }]) {
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
    results.forms[t.id] = { status: resp, fields: audit, allLabeled: audit.every(f => f.hasLabel || f.ariaLabel || f.ariaLabelledBy) };
    await page.screenshot({ path: path.join(__dirname, `access-003-${t.id}.png`) });
  }

  // ---- VAL-ACCESS-004: trigger client-side validation error on /login (only permitted POST surface: empty submit)
  await page.goto(BASE + '/login', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(1000);
  const val = { attempted: false, errorShown: null, inputAriaDescribedBy: null, errorId: null, errorRole: null, wired: null, noNavigation: null };
  val.attempted = true;
  // click submit with empty fields (client-side handler should intercept)
  const submitBtn = await page.$('#login-form button[type=submit], #login-form [type=submit]');
  if (submitBtn) {
    await submitBtn.click();
    await page.waitForTimeout(900);
    val.noNavigation = page.url().replace(/\/$/, '') === BASE + '/login';
    const st = await page.evaluate(() => {
      const out = [];
      for (const input of document.querySelectorAll('#login-form input')) {
        const errId = input.getAttribute('data-error-id') || (input.getAttribute('aria-describedby') || '').split(' ').find(x => x.includes('error'));
        const errEl = errId ? document.getElementById(errId) : null;
        out.push({
          input: input.id,
          ariaDescribedBy: input.getAttribute('aria-describedby'),
          errId,
          errExists: !!errEl,
          errHidden: errEl ? errEl.hidden : null,
          errText: errEl ? errEl.textContent.trim().slice(0, 60) : null,
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
      val.inputAriaDescribedBy = anyShown.ariaDescribedBy;
      val.errorId = anyShown.errId;
      val.errorRole = anyShown.errRole;
      val.wired = !!(anyShown.errId && anyShown.ariaDescribedBy && anyShown.ariaDescribedBy.includes(anyShown.errId));
    }
    await page.screenshot({ path: path.join(__dirname, 'access-004-login-validation-error.png') });
  }
  results.validation = val;

  results.consoleErrors = errors;
  fs.writeFileSync(OUT, JSON.stringify(results, null, 2));
  console.log('DONE');
  console.log(JSON.stringify(results, null, 1));
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
