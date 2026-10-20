/* ── BEAZT auth forms: server-flash → inline field errors ─────────────────
 * Used by /auth/login and /auth/signup (templates/login.html, signup.html).
 *
 * Client-side per-field validation is provided site-wide by the foundation
 * script.js (setupFormValidation on form[novalidate]): required fields,
 * email format, min lengths, confirm-password match, inline .form-error
 * messages, success states, preventDefault + focus on invalid submit.
 *
 * This file adds what the foundation does not cover: server-side validation
 * errors arrive as flashed toasts (base.html flash-container). Here we
 * re-route known field errors into the template's inline error slots
 * (.form-error[data-error-id]) so messages like "Username already taken."
 * are associated with the input that caused them (aria-describedby), then
 * hide the toast container to avoid duplicate display.
 */
(function () {
  'use strict';

  function showErrorInSlot(input, slot, message) {
    var group = input.closest('.form-group');
    slot.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
    var text = document.createElement('span');
    text.textContent = message;
    slot.appendChild(text);
    slot.hidden = false;
    slot.setAttribute('data-error-slot', '');
    input.classList.add('is-error');
    input.classList.remove('is-success');
    input.setAttribute('aria-invalid', 'true');
    if (group) group.classList.add('has-error');
    var described = (input.getAttribute('aria-describedby') || '')
      .split(/\s+/).filter(Boolean);
    if (described.indexOf(slot.id) === -1) described.push(slot.id);
    input.setAttribute('aria-describedby', described.join(' '));
  }

  var FLASH_FIELD_RULES = [
    { re: /user\s*name/i, field: 'username' },
    { re: /email/i, field: 'email' },
    { re: /do\s*not\s*match|don'?t\s*match/i, field: 'confirm_password' },
    { re: /password/i, field: 'password' }
  ];

  function fieldForMessage(text) {
    for (var i = 0; i < FLASH_FIELD_RULES.length; i++) {
      if (FLASH_FIELD_RULES[i].re.test(text)) {
        var candidate = document.getElementById(FLASH_FIELD_RULES[i].field);
        if (candidate && document.getElementById(candidate.getAttribute('data-error-id') || '')) {
          return candidate;
        }
      }
    }
    return null;
  }

  function mapServerFlashes() {
    var container = document.querySelector('.flash-container');
    if (!container) return;
    var unmapped = 0;
    Array.prototype.slice.call(container.querySelectorAll('.flash-message'))
      .forEach(function (msg) {
        var text = (msg.textContent || '').trim();
        if (!text) return;
        // Only validation errors belong in field slots. Success/info
        // messages (e.g. "Password updated. Sign in with your new
        // password." arriving on the login page after a reset) stay as
        // toasts — mapping them into a field would render them as errors.
        var kind = msg.getAttribute('data-flash-kind');
        if (kind === 'success' || kind === 'info') { unmapped++; return; }
        var input = fieldForMessage(text);
        if (input) {
          var slot = document.getElementById(input.getAttribute('data-error-id'));
          showErrorInSlot(input, slot, text);
          msg.parentNode.removeChild(msg);
        } else {
          unmapped++;
        }
      });
    if (!unmapped && !container.querySelector('.flash-message')) {
      container.hidden = true;
    }
  }

  function init() {
    mapServerFlashes();
    // script.js's DOMContentLoaded focusFirstServerError() runs before this
    // file (its <script> tag precedes ours in the document), so on pages
    // server-rendered with a failed-login flash the error state did not
    // exist yet and focus never moved. Re-run the shared routine now that
    // the inline errors are in the DOM (VAL-AUTH-005).
    if (window.BEAZT && typeof window.BEAZT.focusFirstServerError === 'function') {
      window.BEAZT.focusFirstServerError();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
