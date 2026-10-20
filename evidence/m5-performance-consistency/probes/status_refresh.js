// Status page: trigger status refresh sweep
(() => {
  const btn = document.querySelector('[data-refresh], button[data-refresh-status], #refresh-btn, button[class*="refresh"]');
  if (btn) { btn.click(); return {clicked:true, text: btn.textContent.trim().slice(0,40)}; }
  return {clicked:false};
})();
