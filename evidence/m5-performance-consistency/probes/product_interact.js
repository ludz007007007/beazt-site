// Product page: tab switch (ARIA tabs), quantity stepper, tier ladder change
(() => {
  const out = {tab:false, stepper:false, tier:false};
  const tabs = document.querySelectorAll('[role="tab"]');
  if (tabs.length > 1) {
    tabs[1].click();
    out.tab = true;
  }
  const plus = document.querySelector('[data-qty-plus], .qty-plus, button[aria-label*="Increase"], button[aria-label*="increase"]');
  if (plus) { plus.click(); out.stepper = true; }
  const ladder = document.querySelectorAll('input[type="radio"][name="tier_id"]');
  if (ladder.length > 1) { ladder[1].click(); out.tier = true; }
  return out;
})();
