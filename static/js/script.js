(function () {
  /* m5 scrutiny r1: keep a live MediaQueryList, not a one-shot boolean, so a
     preference change mid-session (Settings > accessibility) immediately
     stops the scroll-driven reveal and any other JS-driven motion, matching
     the CSS media-query behaviour. */
  var reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  var reducedMotion = reducedMotionQuery.matches;
  if (typeof reducedMotionQuery.addEventListener === "function") {
    reducedMotionQuery.addEventListener("change", function (e) {
      reducedMotion = e.matches;
    });
  }

  /* ── Header scroll effect ─────────────────────────────── */
  function setupHeaderScroll() {
    var navbar = document.querySelector(".navbar");
    if (!navbar) { return; }
    
    var scrollThreshold = 20;
    var ticking = false;
    
    function updateNavbar() {
      if (window.scrollY > scrollThreshold) {
        navbar.classList.add("scrolled");
      } else {
        navbar.classList.remove("scrolled");
      }
      ticking = false;
    }
    
    window.addEventListener("scroll", function () {
      if (!ticking) {
        window.requestAnimationFrame(updateNavbar);
        ticking = true;
      }
    }, { passive: true });
    
    updateNavbar();
  }

  /* ── Premium mobile menu ──────────────────────────────── */
  function setupMobileMenu() {
    var burger = document.querySelector(".nav-burger");
    var overlay = document.querySelector(".mobile-menu-overlay");
    var menu = document.querySelector(".mobile-menu");

    if (!burger || !menu) { return; }
    
    function openMenu() {
      burger.classList.add("is-active");
      burger.setAttribute("aria-expanded", "true");
      if (overlay) {
        overlay.classList.add("is-visible");
      }
      menu.classList.add("is-open");
      document.body.style.overflow = "hidden";
    }
    
    function closeMenu() {
      burger.classList.remove("is-active");
      burger.setAttribute("aria-expanded", "false");
      if (overlay) {
        overlay.classList.remove("is-visible");
      }
      menu.classList.remove("is-open");
      document.body.style.overflow = "";
    }
    
    burger.addEventListener("click", function () {
      var isOpen = menu.classList.contains("is-open");
      if (isOpen) {
        closeMenu();
      } else {
        openMenu();
      }
    });
    
    if (overlay) {
      overlay.addEventListener("click", closeMenu);
    }
    
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && menu.classList.contains("is-open")) {
        closeMenu();
        burger.focus();
      }
    });
    
    var menuLinks = menu.querySelectorAll("a");
    menuLinks.forEach(function (link) {
      link.addEventListener("click", function () {
        closeMenu();
      });
    });
  }

  function setupReveal() {
    var els = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
    if (!els.length) { return; }
    // VAL-PERF-001: enables the html:not(.js) .reveal fallback in CSS before
    // first paint, so content is never hidden when scripting is unavailable.
    document.documentElement.classList.add("js");

    // Scroll-driven reveal using the existing .reveal / .visible CSS system.
    // Replaces the defer-loaded ScrollReveal CDN, which used to initialize
    // only after this synchronous script had already run, leaving .reveal
    // content stuck at opacity 0 (known load-order bug).
    if (reducedMotion) {
      els.forEach(function (el) { el.classList.add("visible"); });
      return;
    }

    var pending = els;
    var timer = 0;

    function check() {
      var vh = window.innerHeight || document.documentElement.clientHeight;
      for (var i = pending.length - 1; i >= 0; i -= 1) {
        // Reveal anything in the viewport OR already scrolled past (fast
        // flicks can skip elements through the viewport between checks).
        if (pending[i].getBoundingClientRect().top < vh - 40) {
          pending[i].classList.add("visible");
          pending.splice(i, 1);
        }
      }
      if (!pending.length) {
        window.removeEventListener("scroll", onScroll);
        window.removeEventListener("resize", onScroll);
      }
    }

    // setTimeout throttle (not rAF): scroll-driven reveal must also run in
    // environments where rAF frames are throttled or unavailable. Throttle
    // (not debounce) so continuous scrolling still checks every 100ms.
    function onScroll() {
      if (timer) { return; }
      timer = window.setTimeout(function () {
        timer = 0;
        check();
      }, 100);
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    check();
  }

  function setupFaqAccordion() {
    document.querySelectorAll(".faq-question").forEach(function (button) {
      button.addEventListener("click", function () {
        var item = button.closest(".faq-item");
        var alreadyOpen = item.classList.contains("open");
        document.querySelectorAll(".faq-item.open").forEach(function (openItem) {
          openItem.classList.remove("open");
          var openBtn = openItem.querySelector(".faq-question");
          if (openBtn) { openBtn.setAttribute("aria-expanded", "false"); }
        });
        if (!alreadyOpen) {
          item.classList.add("open");
          button.setAttribute("aria-expanded", "true");
        }
      });
    });
    // m5 user-testing r1 (VAL-FAQ-001): in some Chromium builds (observed on
    // Chrome 148 / Electron 42), a stylesheet-declared
    // `transition: grid-template-rows ...` never fires its transition events
    // and the 1fr track resolves to 0px, so FAQ answers never expand — the
    // item highlights but the answer stays collapsed. Feature-detect the
    // transition on a probe element; if it does not run, strip the transition
    // from every answer so they open instantly (content always reachable).
    if (!reducedMotion && document.querySelectorAll(".faq-answer").length) {
      var probe = document.createElement("div");
      probe.style.cssText =
        "position:fixed;left:-9999px;top:0;display:grid;grid-template-rows:0fr;" +
        "transition:grid-template-rows 50ms linear;visibility:hidden;";
      probe.innerHTML = '<div style="overflow:hidden;min-height:0"><p style="height:10px;margin:0"></p></div>';
      document.body.appendChild(probe);
      var probeRan = false;
      var onProbeTransition = function () {
        probeRan = true;
      };
      probe.addEventListener("transitionrun", onProbeTransition);
      probe.addEventListener("transitionstart", onProbeTransition);
      void probe.offsetHeight;
      probe.style.gridTemplateRows = "1fr";
      window.setTimeout(function () {
        probe.removeEventListener("transitionrun", onProbeTransition);
        probe.removeEventListener("transitionstart", onProbeTransition);
        probe.remove();
        if (!probeRan) {
          document.querySelectorAll(".faq-answer").forEach(function (answer) {
            answer.style.transition = "none";
          });
        }
      }, 120);
    }
    // Deep links from the homepage FAQ preview and features grid point at
    // #faq-answer-N anchors; open the targeted item so the answer is visible.
    // Runs on load AND on hashchange: .reveal parents may start hidden and
    // the hash may be set after parse (e.g. in-page navigation), and the
    // FAQ search filter may hide the target — unhide its item/group first.
    function openHashTarget() {
      var hashId = window.location.hash ? window.location.hash.slice(1) : "";
      if (!hashId) { return; }
      var target = document.getElementById(hashId);
      if (!target || !target.classList.contains("faq-answer")) { return; }
      var item = target.closest(".faq-item");
      var btn = item ? item.querySelector(".faq-question") : null;
      if (!item || !btn) { return; }
      item.classList.remove("is-hidden");
      var group = item.closest(".faq-group");
      if (group) { group.classList.remove("is-hidden"); }
      var searchInput = document.getElementById("faq-search");
      if (searchInput && searchInput.value) {
        searchInput.value = "";
        searchInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      item.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
    }
    openHashTarget();
    window.addEventListener("hashchange", openHashTarget);
  }

  function setupFormValidation() {
    var forms = document.querySelectorAll("form[novalidate]");
    if (!forms.length) { return; }

    var validationRules = {
      email: function(value) {
        var emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(value) ? "" : "Please enter a valid email address";
      },
      password: function(value) {
        if (!value) return "Password is required";
        if (value.length < 8) return "Password must be at least 8 characters";
        return "";
      },
      username: function(value) {
        if (!value) return "Username is required";
        if (value.length < 3) return "Username must be at least 3 characters";
        return "";
      },
      confirm_password: function(value, input) {
        // Compare against the primary password field of the SAME form:
        // name="password" (login/signup) or name="new_password" (profile).
        var scope = (input && input.form) ? input.form : document;
        var passwordInput = scope.querySelector('input[name="password"], input[name="new_password"]');
        if (!passwordInput) return "";
        if (value !== passwordInput.value) return "Passwords do not match";
        return "";
      }
    };

    function showError(input, message) {
      var group = input.closest(".form-group");
      if (!group) return;
      
      group.classList.add("has-error");
      group.classList.remove("has-success");
      input.classList.add("is-error");
      input.classList.remove("is-success");
      input.setAttribute("aria-invalid", "true");
      
      var existingError = group.querySelector(".form-error");
      var slot = existingError && (existingError.hasAttribute("hidden") || existingError.hasAttribute("data-error-slot")) ? existingError : null;
      if (existingError && !slot) { existingError.remove(); }

      if (message) {
        var errorDiv = slot || document.createElement("div");
        errorDiv.className = "form-error";
        errorDiv.setAttribute("role", "alert");
        errorDiv.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
        errorDiv.appendChild(document.createTextNode(message));
        errorDiv.hidden = false;
        errorDiv.setAttribute("data-error-slot", "");
        if (!slot) { group.appendChild(errorDiv); }
        // VAL-ACCESS-004: associate the error with its input
        if (errorDiv.id && input.id) {
          var described = (input.getAttribute("aria-describedby") || "").split(/\s+/).filter(function (v) { return v; });
          if (described.indexOf(errorDiv.id) === -1) { described.push(errorDiv.id); }
          input.setAttribute("aria-describedby", described.join(" "));
        }
      }
    }

    function showSuccess(input) {
      var group = input.closest(".form-group");
      if (!group) return;
      
      group.classList.remove("has-error");
      group.classList.add("has-success");
      input.classList.remove("is-error");
      input.classList.add("is-success");
      input.setAttribute("aria-invalid", "false");
      
      var existingError = group.querySelector(".form-error");
      if (existingError) {
        if (existingError.hasAttribute("data-error-slot")) {
          existingError.hidden = true;
          existingError.innerHTML = "";
        } else {
          existingError.remove();
        }
      }
    }

    function clearValidation(input) {
      var group = input.closest(".form-group");
      if (!group) return;
      
      group.classList.remove("has-error", "has-success");
      input.classList.remove("is-error", "is-success");
      input.removeAttribute("aria-invalid");
      
      var existingError = group.querySelector(".form-error");
      if (existingError) {
        if (existingError.hasAttribute("data-error-slot")) {
          existingError.hidden = true;
          existingError.innerHTML = "";
        } else {
          existingError.remove();
        }
      }
    }

    function validateField(input) {
      var value = input.value.trim();
      var type = input.type;
      var name = input.name;
      var required = input.hasAttribute("required");
      var minlength = parseInt(input.getAttribute("minlength"), 10);

      if (required && !value) {
        var label = input.closest(".form-group").querySelector(".form-label");
        var fieldName = label ? label.textContent.trim().replace(/[^\w\s]/gi, "").trim() : name;
        showError(input, fieldName + " is required");
        return false;
      }

      if (type === "email" && value) {
        var error = validationRules.email(value);
        if (error) { showError(input, error); return false; }
      }

      if ((name === "password" || name === "new_password") && value) {
        var error = validationRules.password(value);
        if (error) { showError(input, error); return false; }
      }

      if (name === "confirm_password" && value) {
        var error = validationRules.confirm_password(value, input);
        if (error) { showError(input, error); return false; }
      }

      if (minlength && value && value.length < minlength) {
        showError(input, "Must be at least " + minlength + " characters");
        return false;
      }

      if (value) {
        showSuccess(input);
      } else {
        clearValidation(input);
      }
      
      return true;
    }

    forms.forEach(function(form) {
      var inputs = form.querySelectorAll("input:not([type='submit']):not([type='button']):not([type='checkbox']):not([type='radio'])");
      
      inputs.forEach(function(input) {
        input.addEventListener("blur", function() {
          if (input.value.trim() || input.hasAttribute("required")) {
            validateField(input);
          }
        });
        
        input.addEventListener("input", function() {
          if (input.classList.contains("is-error") || input.classList.contains("is-success")) {
            if (input.classList.contains("is-error")) {
              validateField(input);
            }
          }
        });
      });

      form.addEventListener("submit", function(e) {
        var isValid = true;
        var firstError = null;
        
        inputs.forEach(function(input) {
          if (!validateField(input)) {
            isValid = false;
            if (!firstError) {
              firstError = input;
            }
          }
        });

        var checkboxRequired = form.querySelector("input[type='checkbox'][required]");
        if (checkboxRequired && !checkboxRequired.checked) {
          isValid = false;
          var checkboxGroup = checkboxRequired.closest(".form-group") || checkboxRequired.closest(".form-checkbox");
          if (checkboxGroup) {
            checkboxGroup.classList.add("has-error");
          }
        }

        if (!isValid) {
          e.preventDefault();
          if (firstError) {
            firstError.focus();
          }
        }
      });
    });
  }

  /* ── Server-rendered field errors ─────────────────────────────
     Routes that validate per-field server-side (e.g. /profile) re-render
     the form with visible .form-error slots and .is-error inputs. Move
     focus to the first errored input so keyboard and screen-reader users
     land on the problem, mirroring the client-side submit behaviour. */
  function focusFirstServerError() {
    var errored = document.querySelector("form .form-input.is-error[aria-invalid='true']");
    if (errored) {
      errored.focus();
    }
  }
  /* auth-form.js re-runs this after mapServerFlashes() injects server-rendered
     field errors — its <script> tag executes after this one, so its injected
     errors do not exist yet when the DOMContentLoaded call above runs. */
  window.BEAZT = window.BEAZT || {};
  window.BEAZT.focusFirstServerError = focusFirstServerError;

  /* ── Toasts (flash messages + JS-created) ────────────────
     The region is aria-live=polite. Success toasts carry
     data-autodismiss="4200" and remove themselves; every other kind
     persists until the dismiss control ([data-toast-dismiss], a real
     button) is used. window.BEAZT.toast(message, kind) builds exactly
     the markup partials/flash_toasts.html renders, so flashed and
     scripted notifications behave identically. */
  var TOAST_AUTO_MS = 4200;
  var TOAST_CLOSE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';

  function toastRegion() {
    var region = document.querySelector(".flash-container");
    if (!region) {
      region = document.createElement("div");
      region.className = "flash-container";
      region.setAttribute("aria-live", "polite");
      document.body.appendChild(region);
    }
    return region;
  }

  function dismissToast(toast) {
    if (!toast || toast.classList.contains("is-dismissing")) { return; }
    toast.classList.add("is-dismissing");
    window.setTimeout(function () { toast.remove(); }, 200);
  }

  function scheduleToastAutoDismiss(toast) {
    var ms = parseInt(toast.getAttribute("data-autodismiss"), 10);
    if (!ms) { return; }
    window.setTimeout(function () { dismissToast(toast); }, ms);
  }

  function createToast(message, kind) {
    kind = ["success", "error", "warning", "info"].indexOf(kind) !== -1 ? kind : "info";
    var toast = document.createElement("div");
    toast.className = "flash-message flash-" + kind + (kind === "success" ? "" : " flash-persist");
    toast.setAttribute("role", "status");
    toast.setAttribute("data-flash-kind", kind);
    if (kind === "success") { toast.setAttribute("data-autodismiss", String(TOAST_AUTO_MS)); }
    var body = document.createElement("div");
    body.className = "flash-message__body";
    body.textContent = message;
    toast.appendChild(body);
    var close = document.createElement("button");
    close.type = "button";
    close.className = "flash-close";
    close.setAttribute("data-toast-dismiss", "");
    close.setAttribute("aria-label", "Dismiss notification");
    close.innerHTML = TOAST_CLOSE_SVG;
    toast.appendChild(close);
    toastRegion().appendChild(toast);
    scheduleToastAutoDismiss(toast);
    return toast;
  }

  window.BEAZT = window.BEAZT || {};
  window.BEAZT.toast = createToast;
  window.BEAZT.openModal = openModal;
  window.BEAZT.closeModal = closeModal;

  function setupToasts() {
    document.querySelectorAll(".flash-message[data-autodismiss]").forEach(scheduleToastAutoDismiss);
    document.addEventListener("click", function (e) {
      var control = e.target.closest ? e.target.closest("[data-toast-dismiss]") : null;
      if (control) { dismissToast(control.closest(".flash-message")); }
    });
  }

  /* ── Modal dialogs ──────────────────────────────────────
     partials/modal.html renders [data-modal] dialogs. Openers carry
     data-modal-open="#id"; [data-modal-close], Escape and backdrop
     clicks close (the backdrop is ignored on [data-modal-static]
     destructive confirms). Focus is trapped inside the panel while a
     modal is open and restored to its opener on close. */
  var activeModal = null;
  var modalOpener = null;

  function modalFocusables(modal) {
    var selector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    var nodes = modal.querySelectorAll(selector);
    var visible = [];
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].offsetParent !== null || nodes[i] === document.activeElement) { visible.push(nodes[i]); }
    }
    return visible;
  }

  function openModal(modal, opener) {
    if (activeModal && activeModal !== modal) { closeModal(false); }
    modalOpener = opener || document.activeElement;
    modal.hidden = false;
    document.documentElement.classList.add("has-open-modal");
    activeModal = modal;
    var focusables = modalFocusables(modal);
    var target = focusables[0] || modal.querySelector(".modal-panel");
    if (target) { target.focus(); }
  }

  function closeModal(restoreFocus) {
    var modal = activeModal;
    if (!modal) { return; }
    modal.hidden = true;
    document.documentElement.classList.remove("has-open-modal");
    activeModal = null;
    if (restoreFocus && modalOpener && typeof modalOpener.focus === "function") { modalOpener.focus(); }
    modalOpener = null;
  }

  function setupModals() {
    document.addEventListener("click", function (e) {
      if (!e.target.closest) { return; }
      var opener = e.target.closest("[data-modal-open]");
      if (opener) {
        var modal = document.querySelector(opener.getAttribute("data-modal-open"));
        if (modal) { e.preventDefault(); openModal(modal, opener); }
        return;
      }
      if (!activeModal) { return; }
      if (e.target.closest("[data-modal-close]")) { closeModal(true); return; }
      var backdrop = e.target.closest("[data-modal-backdrop]");
      if (backdrop && !activeModal.hasAttribute("data-modal-static")) { closeModal(true); }
    });
    document.addEventListener("keydown", function (e) {
      if (!activeModal) { return; }
      if (e.key === "Escape") { closeModal(true); return; }
      if (e.key !== "Tab") { return; }
      var focusables = modalFocusables(activeModal);
      if (!focusables.length) { return; }
      var first = focusables[0];
      var last = focusables[focusables.length - 1];
      var inside = activeModal.contains(document.activeElement);
      if (e.shiftKey && (document.activeElement === first || !inside)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (document.activeElement === last || !inside)) {
        e.preventDefault();
        first.focus();
      }
    });
  }

  /* ── Destructive-action confirm dialog (admin) ──────────
     partials/confirm_dialog.html is included once per shell. Any form or
     submit button carrying data-confirm="message" has its submit blocked,
     the dialog filled in and opened through the modal system; confirming
     resumes the original submit (requestSubmit with the original trigger).
     data-confirm-title overrides the heading, data-require-checked guards
     bulk actions (no selection → error toast, no dialog), and
     data-check-all re-selects every named checkbox before resuming. */
  function setupConfirmDialogs() {
    var dialog = document.getElementById("confirm-dialog");
    var titleEl = document.getElementById("confirm-dialog-title");
    var msgEl = document.getElementById("confirm-dialog-message");
    var acceptBtn = document.getElementById("confirm-dialog-accept");
    if (!dialog || !titleEl || !msgEl || !acceptBtn) { return; }
    var pendingForm = null;
    var pendingTrigger = null;

    function resume() {
      var form = pendingForm;
      var trigger = pendingTrigger;
      pendingForm = null;
      pendingTrigger = null;
      if (!form) { return; }
      form.setAttribute("data-confirmed", "1");
      var checkAll = attrFrom(form, trigger, "data-check-all");
      if (checkAll) {
        var boxes = form.querySelectorAll('input[type="checkbox"][name="' + checkAll + '"]');
        for (var i = 0; i < boxes.length; i++) { boxes[i].checked = true; }
      }
      if (typeof form.requestSubmit === "function" && trigger && trigger.form === form) {
        form.requestSubmit(trigger);
      } else {
        form.submit();
      }
    }

    // Submit-level attributes win over the form's (Delete Selected vs Delete
    // All share one bulk form but confirm differently).
    function attrFrom(form, trigger, name) {
      return (trigger && trigger.getAttribute(name)) || form.getAttribute(name);
    }

    function blockedSubmit(e) {
      var form = e.target;
      if (!form || !form.hasAttribute) { return; }
      var trigger = e.submitter || null;
      var message = attrFrom(form, trigger, "data-confirm");
      var title = attrFrom(form, trigger, "data-confirm-title");
      if (!message && !title) { return; }
      if (form.getAttribute("data-confirmed") === "1") {
        form.removeAttribute("data-confirmed");
        return;
      }
      var requireSel = attrFrom(form, trigger, "data-require-checked");
      if (requireSel && !form.querySelector(requireSel + ":checked")) {
        e.preventDefault();
        if (window.BEAZT && window.BEAZT.toast) {
          window.BEAZT.toast("Select at least one item first.", "error");
        }
        return;
      }
      e.preventDefault();
      pendingForm = form;
      pendingTrigger = trigger;
      titleEl.textContent = title || "Please confirm";
      msgEl.textContent = message || "Are you sure? This cannot be undone.";
      openModal(dialog, pendingTrigger);
    }

    acceptBtn.addEventListener("click", function () {
      closeModal(true);
      resume();
    });

    // Capture phase: sits ahead of any per-form handlers.
    document.addEventListener("submit", blockedSubmit, true);
  }

  /* ── Bulk-table select-all (admin) ──────────────────────
     A [data-select-all] checkbox toggles every [data-bulk-item] checkbox in
     its scope: value "form" scopes to the closest form, otherwise the value
     is a selector for the container (table, tbody, …). */
  function setupBulkSelect() {
    document.addEventListener("change", function (e) {
      var toggle = e.target.closest ? e.target.closest("[data-select-all]") : null;
      if (!toggle) { return; }
      var scopeValue = toggle.getAttribute("data-select-all");
      var scope = scopeValue === "form" ? toggle.closest("form") : document.querySelector(scopeValue);
      if (!scope) { return; }
      var boxes = scope.querySelectorAll('input[type="checkbox"][data-bulk-item]');
      for (var i = 0; i < boxes.length; i++) { boxes[i].checked = toggle.checked; }
    });
  }

  /* ── Catalogue filter auto-submit (VAL-ST-002) ────────── */
  function setupAutoFilters() {
    var form = document.querySelector("form[data-autosubmit]");
    if (!form) { return; }
    // Flag that the form is live: CSS hides the no-JS "Apply" fallback.
    form.classList.add("filter-bar--auto");

    var search = form.querySelector('input[name="q"]');
    var debounceTimer = 0;
    var lastSubmittedQ = search ? search.value.trim() : "";

    // Rebuild the GET query from the form, dropping empty params so URLs
    // stay clean (server contract unchanged: params present = applied).
    // A select sitting on its first (default) option contributes nothing.
    function formUrl() {
      var params = new URLSearchParams();
      Array.prototype.forEach.call(form.elements, function (el) {
        if (!el.name) { return; }
        if (el.tagName === "SELECT" && el.selectedIndex === 0) { return; }
        var value = (el.value || "").trim();
        if (value) { params.set(el.name, value); }
      });
      var qs = params.toString();
      return (form.getAttribute("action") || window.location.pathname) + (qs ? "?" + qs : "");
    }

    function submit() {
      try { sessionStorage.setItem("beazt.filterFocus", "1"); } catch (e) { /* private mode */ }
      window.location.href = formUrl();
    }

    // Selects apply immediately; the search box goes through the debounce.
    form.addEventListener("change", function (e) {
      if (e.target === search) { return; }
      submit();
    });

    // Explicit submits (Apply button, Enter key) take the same clean-URL
    // path instead of the browser's q=&game=… serialisation.
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      submit();
    });

    if (!search) { return; }

    search.addEventListener("input", function () {
      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(function () {
        if (search.value.trim() !== lastSubmittedQ) {
          lastSubmittedQ = search.value.trim();
          submit();
        }
      }, 400);
    });

    // After an auto-submit navigation the page reloaded under the user's
    // fingers — restore focus and put the caret at the end so typing flows.
    var refocus = false;
    try {
      refocus = sessionStorage.getItem("beazt.filterFocus") === "1";
      sessionStorage.removeItem("beazt.filterFocus");
    } catch (e) { /* private mode */ }
    if (refocus) {
      search.focus();
      try { search.setSelectionRange(search.value.length, search.value.length); } catch (err) { /* type=search quirk */ }
    }
  }

  /* ── Status board: data refresh + sweep (VAL-ST-007) ───
     While /status is open, the board quietly re-fetches the page every
     60s (skipped while the tab is hidden). Rows whose status or freshness
     changed update in place from the server-rendered markup — the server
     stays the single source of every label and date — and a one-shot amber
     sheen (700ms, .is-swept) passes through them: the site's only
     signature motion. Reduced motion: data still updates, the sweep never
     runs. window.BEAZT.statusRefresh() exposes the same path for tests. */
  function setupStatusBoard() {
    var board = document.querySelector("[data-status-board]");
    if (!board) { return; }

    function sweepRow(row) {
      if (reducedMotion) { return; }
      row.classList.add("is-swept");
      window.setTimeout(function () { row.classList.remove("is-swept"); }, 900);
    }

    function applyRefresh(doc) {
      var changed = 0;
      Array.prototype.forEach.call(board.querySelectorAll("[data-status-row]"), function (row) {
        var slug = row.getAttribute("data-status-row");
        var next = doc.querySelector('[data-status-row="' + slug + '"]');
        if (!next) { return; }
        var statusChanged = next.getAttribute("data-status") !== row.getAttribute("data-status");
        var fresh = row.querySelector("[data-status-fresh]");
        var nextFresh = next.querySelector("[data-status-fresh]");
        var norm = function (html) { return (html || "").replace(/\s+/g, " ").trim(); };
        var freshChanged = fresh && nextFresh && norm(nextFresh.innerHTML) !== norm(fresh.innerHTML);
        if (!statusChanged && !freshChanged) { return; }
        if (statusChanged) { row.setAttribute("data-status", next.getAttribute("data-status")); }
        var pill = row.querySelector("[data-status-pill]");
        var nextPill = next.querySelector("[data-status-pill]");
        if (pill && nextPill) { pill.innerHTML = nextPill.innerHTML; }
        if (fresh && nextFresh) { fresh.innerHTML = nextFresh.innerHTML; }
        sweepRow(row);
        changed++;
      });
      // Summary numbers follow the server's own markup (single formatting source).
      ["count", "verified"].forEach(function (key) {
        var local = document.querySelector("[data-status-" + key + "-wrap]");
        var remote = doc.querySelector("[data-status-" + key + "-wrap]");
        if (local && remote) { local.innerHTML = remote.innerHTML; }
      });
      if (changed) {
        var live = document.querySelector("[data-status-live]");
        if (live) {
          live.textContent = "Status board refreshed — " + changed +
            (changed === 1 ? " product changed." : " products changed.");
        }
      }
      return changed;
    }

    var refreshing = false;
    function statusRefresh() {
      if (refreshing || document.hidden) { return Promise.resolve(0); }
      refreshing = true;
      return fetch(window.location.href, { cache: "no-store" })
        .then(function (res) { return res.ok ? res.text() : ""; })
        .then(function (html) {
          if (!html) { return 0; }
          return applyRefresh(new DOMParser().parseFromString(html, "text/html"));
        })
        .catch(function () { return 0; })
        .then(function (changed) { refreshing = false; return changed; });
    }

    window.BEAZT = window.BEAZT || {};
    window.BEAZT.statusRefresh = statusRefresh;
    window.setInterval(statusRefresh, 60000);
  }

  function hydrateIcons() {
    // Lucide is injected AFTER the page has loaded (see loadDeferred below):
    // its 440KB bundle must not compete with the render-blocking CSS for
    // bandwidth on slow connections. Icons are decorative; hydrate late.
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      try { window.lucide.createIcons(); } catch (error) { console.error("Lucide render failed", error); }
    }
  }

  /* ── Product page: ARIA tabs (roving tabindex) ──────────
     Tabs follow the WAI-ARIA pattern: one tab in the tab order at a time,
     Arrow/Home/End keys move focus AND select (automatic activation), and
     the newly selected tab receives focus. The server renders the first
     tab selected, so the pattern degrades to a static panel without JS. */
  window.tabsState = function (tabIds) {
    return {
      activeTab: tabIds[0],
      tabIds: tabIds,
      select: function (id) { this.activeTab = id; },
      onTablistKeydown: function (e) {
        var i = this.tabIds.indexOf(this.activeTab);
        var j = null;
        if (e.key === "ArrowRight") { j = (i + 1) % this.tabIds.length; }
        else if (e.key === "ArrowLeft") { j = (i - 1 + this.tabIds.length) % this.tabIds.length; }
        else if (e.key === "Home") { j = 0; }
        else if (e.key === "End") { j = this.tabIds.length - 1; }
        if (j === null) { return; }
        e.preventDefault();
        this.activeTab = this.tabIds[j];
        var self = this;
        this.$nextTick(function () {
          var el = document.getElementById("tab-" + self.tabIds[j]);
          if (el) { el.focus(); }
        });
      }
    };
  };

  /* ── Product page: media gallery ─────────────────────────
     Thumbs are real buttons (keyboard-selectable); the polite live region
     announces the current screenshot. `images` arrives server-rendered. */
  window.galleryState = function (images) {
    return {
      images: images,
      active: 0,
      select: function (i) { this.active = Math.max(0, Math.min(i, images.length - 1)); },
      get announcement() {
        return "Screenshot " + (this.active + 1) + " of " + this.images.length;
      }
    };
  };

  function injectVendor(src) {
    var script = document.createElement("script");
    script.src = src;
    document.head.appendChild(script);
    return script;
  }

  /* ── Image fallback wiring ────────────────────────────── */
  // Cards carry data-fallback="/cheat-image/<slug>": when a set-but-broken
  // image_url 404s, swap to the generated typographic cover. Error events
  // do not bubble, so the listener captures at the document level.
  function setupImageFallbacks() {
    document.addEventListener("error", function (e) {
      var img = e.target;
      if (!(img instanceof HTMLImageElement)) { return; }
      var fb = img.getAttribute("data-fallback");
      if (fb && img.getAttribute("src") !== fb) {
        img.src = fb;
      }
    }, true);
  }

  function loadDeferred() {
    if (!window.lucide) {
      var icons = injectVendor("/static/js/vendor/lucide.min.js");
      icons.onload = hydrateIcons;
    }
    if (!window.Alpine) {
      // Alpine's CDN build auto-starts when injected after DOMContentLoaded
      // (it checks document.readyState), so deferred interaction components
      // initialize as soon as it arrives.
      injectVendor("/static/js/vendor/alpine.min.js");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setupHeaderScroll();
      setupMobileMenu();
      setupReveal();
      setupFaqAccordion();
      setupFormValidation();
      focusFirstServerError();
      setupToasts();
      setupModals();
      setupConfirmDialogs();
      setupBulkSelect();
      setupAutoFilters();
      setupStatusBoard();
      setupImageFallbacks();
      hydrateIcons();
    });
    window.addEventListener("load", loadDeferred);
  } else {
    setupHeaderScroll();
    setupMobileMenu();
    setupReveal();
    setupFaqAccordion();
    setupFormValidation();
    focusFirstServerError();
    setupToasts();
    setupModals();
    setupConfirmDialogs();
    setupBulkSelect();
    setupAutoFilters();
    setupStatusBoard();
    setupImageFallbacks();
    hydrateIcons();
    loadDeferred();
  }
})();
