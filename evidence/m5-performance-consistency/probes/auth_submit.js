// Auth login: submit empty form to trigger inline errors
(() => {
  const form = document.querySelector('form');
  if (!form) return {form:false};
  form.requestSubmit();
  return {form:true, errors: document.querySelectorAll('[role="alert"]').length};
})();
