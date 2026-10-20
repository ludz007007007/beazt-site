// Cheats page: apply search + status filter (auto-submitting filters)
(() => {
  const q = document.querySelector('input[name="q"]');
  if (q) { q.value = 'rust'; q.dispatchEvent(new Event('input', {bubbles:true})); }
  const form = q && q.closest('form');
  if (form) form.requestSubmit();
  else if (q) { q.dispatchEvent(new Event('change', {bubbles:true})); }
  return {q: !!q, submitted: !!form};
})();
