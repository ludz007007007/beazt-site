// My Keys: key filter buttons + copy button
(() => {
  const out = {filter:false, copy:false};
  const fbtns = document.querySelectorAll('[data-key-filter], .key-filter button, button[data-filter]');
  if (fbtns.length > 1) { fbtns[1].click(); out.filter = true; }
  const copy = document.querySelector('[data-copy-key], button[aria-label*="Copy"], .key-card [data-copy]');
  if (copy) { copy.click(); out.copy = true; }
  return out;
})();
