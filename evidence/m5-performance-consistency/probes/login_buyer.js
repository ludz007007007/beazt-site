(() => {
  const u = document.querySelector('#username, input[name="username"]');
  const p = document.querySelector('#password, input[name="password"]');
  if (!u || !p) return {ok:false};
  u.value = 'demo_buyer';
  p.value = 'DemoBuyer!2026';
  u.dispatchEvent(new Event('input', {bubbles:true}));
  p.dispatchEvent(new Event('input', {bubbles:true}));
  const f = u.closest('form');
  f.requestSubmit();
  return {ok:true};
})();
