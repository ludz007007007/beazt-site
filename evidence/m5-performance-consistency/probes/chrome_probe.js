(() => {
  const styleOf = (el, props) => {
    if (!el) return null;
    const cs = getComputedStyle(el);
    const out = {};
    props.forEach(p => { out[p] = cs.getPropertyValue(p); });
    return out;
  };
  const props = ['background-color','color','border-radius','border-top-color','padding-top','min-height','font-family','font-size','font-weight','letter-spacing','box-shadow'];
  const r = {};
  r.headerShell = styleOf(document.querySelector('.site-header'), ['background-color','border-bottom-color','min-height','position']);
  r.brandLogo = styleOf(document.querySelector('.brand__logo'), ['width','height']);
  r.navLink = styleOf(document.querySelector('.site-nav a, .site-header nav a'), props);
  r.signIn = styleOf(document.querySelector('.site-header .btn, .site-header a[class*="btn"]'), props);
  r.skipLink = styleOf(document.querySelector('.skip-link'), props);
  r.footerCol = styleOf(document.querySelector('.site-footer h3, .site-footer h4, .site-footer strong'), ['color','font-size','letter-spacing','text-transform']);
  r.footerLink = styleOf(document.querySelector('.site-footer a'), ['color','font-size']);
  r.mainPad = styleOf(document.querySelector('.site-main'), ['padding-top']);
  const root = getComputedStyle(document.documentElement);
  r.tokens = {};
  ['--bg-base','--bg-elevated','--text-primary','--text-secondary','--text-muted','--accent','--border-subtle','--radius-md','--radius-lg','--space-4','--space-6','--duration-fast','--ease-standard','--control-height','--header-height'].forEach(t => { r.tokens[t] = root.getPropertyValue(t).trim(); });
  return r;
})();
