(() => {
  const pick = (sel) => document.querySelector(sel);
  const styleOf = (el, props) => {
    if (!el) return null;
    const cs = getComputedStyle(el);
    const out = {};
    props.forEach(p => { out[p] = cs.getPropertyValue(p); });
    return out;
  };
  const props = ['background-color','color','border-radius','border-top-width','border-top-color','padding-top','padding-bottom','min-height','font-family','font-size','font-weight','letter-spacing','box-shadow'];
  const result = {};
  result.btnPrimary = styleOf(pick('.btn.btn--primary, .btn-primary, .btn--primary'), props);
  result.btnSecondary = styleOf(pick('.btn--secondary, .btn-secondary, .btn.btn--ghost'), props);
  result.chip = styleOf(pick('.chip'), props);
  result.statusPill = styleOf(pick('.status-pill, [class*="status-pill"]'), props);
  result.card = styleOf(pick('.card, .product-card, .pcard'), props);
  result.heading = styleOf(pick('h1, h2'), props);
  result.containerPad = styleOf(pick('.container, .site-main > *, main'), ['padding-left','max-width']);
  // token values as resolved on this page
  const root = getComputedStyle(document.documentElement);
  result.tokens = {};
  ['--bg-base','--bg-elevated','--text-primary','--text-secondary','--text-muted','--accent','--radius-md','--radius-lg','--space-4','--space-6','--duration-fast','--ease-standard','--control-height'].forEach(t => { result.tokens[t] = root.getPropertyValue(t).trim(); });
  return result;
})();
