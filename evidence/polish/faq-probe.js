const { chromium } = require('E:\\github\\rust beazt\\BEAZT-WEBSITE\\node_modules\\playwright');
(async () => {
  const b = await chromium.launch();
  const p = await (await b.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
  await p.goto('http://127.0.0.1:5000/faq', { waitUntil: 'networkidle' });
  await p.waitForTimeout(1000);
  const info = await p.evaluate(() => {
    const els = Array.from(document.querySelectorAll('.faq-question, details summary, button[aria-expanded]')).slice(0, 3);
    return els.map(el => ({
      tag: el.tagName, cls: el.className, ariaExpanded: el.getAttribute('aria-expanded'),
      ariaControls: el.getAttribute('aria-controls'),
      parentTag: el.parentElement.tagName, parentCls: el.parentElement.className,
      outer: el.outerHTML.slice(0, 220),
    }));
  });
  console.log(JSON.stringify(info, null, 1));
  const btn = await p.$('button.faq-question');
  if (!btn) { console.log('no button.faq-question on /faq'); await b.close(); return; }
  const binfo = await btn.evaluate(el => ({ tag: el.tagName, expanded: el.getAttribute('aria-expanded'), controls: el.getAttribute('aria-controls') }));
  await btn.focus();
  await p.keyboard.press('Enter');
  await p.waitForTimeout(600);
  const after = await p.evaluate(() => {
    const q = document.querySelector('.faq-question');
    const panel = q && q.getAttribute('aria-controls') ? document.getElementById(q.getAttribute('aria-controls')) : null;
    return {
      btnExpanded: q ? q.getAttribute('aria-expanded') : 'n/a',
      panelDisplay: panel ? getComputedStyle(panel).display : 'n/a',
      panelH: panel ? Math.round(panel.getBoundingClientRect().height) : 'n/a',
    };
  });
  console.log('before:', JSON.stringify(binfo), 'after:', JSON.stringify(after));
  await p.keyboard.press('Enter');
  await p.waitForTimeout(600);
  const after2 = await p.evaluate(() => {
    const q = document.querySelector('.faq-question');
    const panel = q && q.getAttribute('aria-controls') ? document.getElementById(q.getAttribute('aria-controls')) : null;
    return { btnExpanded: q ? q.getAttribute('aria-expanded') : 'n/a', panelDisplay: panel ? getComputedStyle(panel).display : 'n/a', panelH: panel ? Math.round(panel.getBoundingClientRect().height) : 'n/a' };
  });
  console.log('after2:', JSON.stringify(after2));
  await b.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
