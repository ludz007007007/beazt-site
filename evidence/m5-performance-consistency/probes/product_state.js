(() => {
  const tab = document.querySelector('[role="tab"][aria-selected="true"]');
  const panel = tab ? document.getElementById(tab.getAttribute('aria-controls')) : null;
  const qty = document.querySelector('.pd-qty-input');
  return {
    activeTab: tab ? tab.id : null,
    panelVisible: panel ? !panel.hidden : null,
    qty: qty ? qty.value : null
  };
})();
