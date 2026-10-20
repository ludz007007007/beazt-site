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
  if (!sess) throw new Error('no session cookie found in jar');
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  await ctx.addCookies([{ name: 'session', value: sess, domain: 'localhost', path: '/' }]);
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });

  await page.goto('http://localhost:5000/admin/settings', { waitUntil: 'networkidle' });
  // allow Alpine to hydrate
  await page.waitForTimeout(800);

  const structure = await page.evaluate(() => {
    const forms = Array.from(document.querySelectorAll('form'));
    const nested = forms.filter(f => f.parentElement && f.parentElement.closest('form'));
    const btn = document.querySelector('button[form="chairfbi-test-form"]');
    const testForm = document.getElementById('chairfbi-test-form');
    const outerForm = document.querySelector('form[enctype="multipart/form-data"]');
    return {
      formCount: forms.length,
      nestedFormCount: nested.length,
      buttonExists: !!btn,
      buttonText: btn ? btn.textContent.trim() : null,
      buttonFormAction: btn ? btn.formAction : null,
      buttonFormId: btn && btn.form ? btn.form.id : null,
      testFormAction: testForm ? testForm.getAttribute('action') : null,
      testFormMethod: testForm ? testForm.getAttribute('method') : null,
      testFormHasCsrf: testForm ? !!testForm.querySelector('input[name="csrf_token"][value]') : false,
      outerFormHasCsrf: outerForm ? !!outerForm.querySelector('input[name="csrf_token"][value]') : false,
      outerFormFieldCount: outerForm ? outerForm.elements.length : 0,
      saveButtonInOuter: outerForm ? !!outerForm.querySelector('button[type="submit"].btn-primary') : false,
    };
  });
  console.log('STRUCTURE:', JSON.stringify(structure, null, 2));

  // Click Test Connection -> should POST the test form to /admin/settings/chairfbi-test
  // (empty token in DB -> flash "Please enter an API token first." after redirect)
  const resp = await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle' }),
    page.evaluate(() => document.querySelector('button[form="chairfbi-test-form"]').click()),
  ]);
  console.log('AFTER_CLICK_URL:', page.url());
  const flash = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('.flash-message, [class*="flash"], .cf-alert'));
    return els.map(e => e.textContent.trim()).filter(t => t.length > 0 && t.length < 200);
  });
  console.log('FLASH_MESSAGES:', JSON.stringify(flash));
  console.log('CONSOLE_ERRORS:', JSON.stringify(consoleErrors));

  await page.screenshot({ path: 'evidence\\polish\\admin-unnest-form\\after-test-click.png', fullPage: false });
  await browser.close();
})().catch(e => { console.error('FAIL:', e); process.exit(1); });
