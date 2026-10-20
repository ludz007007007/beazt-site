"""Component-library contracts (feature m1-component-library).

Locks in the five shared components:
  1. status pill = the ONE risk taxonomy, availability badge separate;
  2. toasts: success auto-dismisses (4.2s), errors persist + dismissible,
     announced politely;
  3. modal dialog: accessible markup fixture + the script.js behaviours;
  4. form system (.form-group/.form-label/.form-input + inline errors) as
     the only storefront form markup;
  5. one empty-state partial everywhere + skeletons only for genuinely
     async content (the keys dashboard pre-hydration state).
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(ROOT, "templates")
SCRIPT_JS = os.path.join(ROOT, "static", "js", "script.js")


def _template(rel):
    with open(os.path.join(TEMPLATES_DIR, rel.replace("/", os.sep)), encoding="utf-8") as fh:
        return fh.read()


def _markup(rel):
    """Template source with {# comments #} stripped, so docstring mentions
    (e.g. the pill partial explaining what must NEVER go in it) don't trip
    vocabulary scans."""
    return re.sub(r"\{#.*?#\}", "", _template(rel), flags=re.S)


def _storefront_templates():
    for dirpath, dirnames, filenames in os.walk(TEMPLATES_DIR):
        dirnames[:] = [d for d in dirnames if d != "admin"]
        for fn in filenames:
            if not fn.endswith(".html"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), TEMPLATES_DIR).replace("\\", "/")
            yield rel


def _render_partial(app, name, **context):
    return app.jinja_env.get_template(name).render(**context)


def _script():
    with open(SCRIPT_JS, encoding="utf-8") as fh:
        return fh.read()


# ── 1. Status taxonomy + availability badge ──────────────────────────────

def test_status_pill_is_the_single_risk_taxonomy(app):
    from utils.catalogue import STATUS_LABELS

    assert set(STATUS_LABELS) == {"undetected", "updating", "risky", "detected", "down"}
    for status, label in STATUS_LABELS.items():
        html = _render_partial(app, "partials/status_pill.html", status=status, label=label)
        assert 'class="status-pill status-pill--%s"' % status in html
        assert "<span class=\"status-pill-label\">%s</span>" % label in html


def test_status_pill_never_carries_availability():
    pill = _markup("partials/status_pill.html")
    for word in ("In stock", "Sold out", "Private build"):
        assert word not in pill


@pytest.mark.parametrize("key,label", [
    ("in_stock", "In stock"),
    ("sold_out", "Sold out"),
    ("private", "Private build"),
])
def test_availability_badge_vocabulary(app, key, label):
    html = _render_partial(app, "partials/availability_badge.html", availability=key, show_in_stock=True)
    assert label in html
    assert "badge-availability--%s" % key in html


def test_availability_badge_quiet_by_default_and_rejects_unknown(app):
    assert "In stock" not in _render_partial(app, "partials/availability_badge.html", availability="in_stock")
    assert "In stock" in _render_partial(app, "partials/availability_badge.html", availability="in_stock", show_in_stock=True)
    assert _render_partial(app, "partials/availability_badge.html", availability="bogus").strip() == ""


def test_availability_badge_never_carries_risk_taxonomy():
    badge = _markup("partials/availability_badge.html")
    for word in ("Undetected", "Updating", "Risky", "Detected", "Down"):
        assert word not in badge


def test_product_card_composes_pill_and_badge():
    card = _template("partials/product_card.html")
    assert 'include "partials/status_pill.html"' in card
    assert 'include "partials/availability_badge.html"' in card
    # The old inline "Private build"/"Sold out" spans are gone.
    assert "Private build</span>" not in card
    assert "Sold out</span>" not in card


def test_status_pill_markup_comes_only_from_the_partial():
    for rel in _storefront_templates():
        if rel == "partials/status_pill.html":
            continue
        assert "status-pill--" not in _template(rel), rel


# ── 2. Toasts ────────────────────────────────────────────────────────────

def _toast_node(html, kind):
    return re.search(r'<div class="flash-message flash-%s[^"]*"[^>]*>' % kind, html)


def test_error_toast_persists_with_keyboard_dismissible_control(client, post_form):
    resp = post_form(client, "/auth/login", {"username": "ghost", "password": "wrong-pass"}, follow_redirects=True)
    html = resp.get_data(as_text=True)
    node = _toast_node(html, "error")
    assert node, "failed login should flash an error toast"
    assert "flash-persist" in node.group(0)
    assert "data-autodismiss" not in node.group(0)
    # Announced politely; dismiss is a real labelled button (keyboard-operable).
    assert 'aria-live="polite"' in html
    assert re.search(r'<button[^>]*data-toast-dismiss[^>]*>', html)
    assert 'aria-label="Dismiss notification"' in html


def test_success_toast_auto_dismisses(buyer_client, post_form):
    resp = post_form(buyer_client, "/profile", {"email": "buyer@beazt.test"}, follow_redirects=True)
    html = resp.get_data(as_text=True)
    node = _toast_node(html, "success")
    assert node, "profile save should flash a success toast"
    assert 'data-autodismiss="4200"' in node.group(0)
    assert "flash-persist" not in node.group(0)


def test_toast_partial_contract():
    src = _template("partials/flash_toasts.html")
    assert 'aria-live="polite"' in src
    assert "data-toast-dismiss" in src
    assert 'aria-label="Dismiss notification"' in src
    assert 'data-autodismiss="4200"' in src


def test_script_drives_toast_persistence_and_dismiss():
    js = _script()
    assert "data-autodismiss" in js, "auto-dismiss must be opt-in per toast"
    assert "data-toast-dismiss" in js, "dismiss control must be wired"
    assert "window.BEAZT.toast" in js, "JS-created toasts share the markup"
    assert "aria-live" in js, "created toast region announces politely"
    assert "setupFlashDismiss" not in js, "blanket 4200ms fade of every toast is gone"


# ── 3. Modal dialog ──────────────────────────────────────────────────────

def test_modal_partial_markup_contract(app):
    html = _render_partial(
        app, "partials/modal.html",
        modal_id="demo", modal_title="Confirm purchase",
        modal_content="<p>Proceed with this order?</p>",
        modal_footer='<button class="btn btn-primary">Confirm</button>',
    )
    for fragment in (
        'id="demo"', "data-modal", "hidden", 'role="dialog"', 'aria-modal="true"',
        'aria-labelledby="demo-title"', 'aria-describedby="demo-body"',
        'id="demo-title"', 'id="demo-body"', "data-modal-backdrop",
        '<button type="button" class="modal-close" data-modal-close',
        'aria-label="Close dialog"',
    ):
        assert fragment in html, fragment
    assert "data-modal-static" not in html
    assert "modal-panel--" not in html  # default size


def test_modal_partial_static_and_size_variants(app):
    static = _render_partial(app, "partials/modal.html", modal_id="x", modal_title="T", modal_content="c", modal_static=True)
    assert "data-modal-static" in static
    lg = _render_partial(app, "partials/modal.html", modal_id="x", modal_title="T", modal_content="c", modal_size="lg")
    assert "modal-panel--lg" in lg


def test_modal_hidden_guard_in_built_css(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    assert ".modal[hidden]" in css, "flex display must not defeat the hidden attribute"


def test_script_implements_modal_behaviours():
    js = _script()
    for marker in (
        "data-modal-open", "data-modal-close", "data-modal-static",
        '"Escape"', "modalFocusables", "modalOpener",
    ):
        assert marker in js, marker


# ── 4. Form system as the only form markup ───────────────────────────────

@pytest.mark.parametrize("page", ["/auth/login", "/auth/signup"])
def test_auth_forms_on_the_form_system(client, page):
    html = client.get(page).get_data(as_text=True)
    assert "form-group" in html and "form-label" in html and "form-input" in html
    assert 'role="alert"' in html and "form-error" in html


def test_profile_form_on_the_form_system_without_inline_styles(buyer_client):
    html = buyer_client.get("/profile").get_data(as_text=True)
    assert "form-group" in html and "form-label" in html and "form-input" in html
    assert 'role="alert"' in html
    assert "style=" not in html


def test_review_form_uses_the_form_system():
    html = _template("product.html")
    assert 'class="review-form" novalidate' in html
    assert "review-form-row" not in html
    assert 'class="form-select" required' in html
    assert 'class="form-input" rows="4" required' in html
    assert html.count('class="form-error"') >= 3


def test_no_inline_styled_form_controls_in_storefront():
    pattern = re.compile(r"<(input|select|textarea)\b[^>]*\sstyle=", re.I)
    for rel in _storefront_templates():
        assert not pattern.search(_template(rel)), rel


# ── 5. Empty states + skeleton rules ─────────────────────────────────────

def test_empty_states_render_via_the_shared_partial():
    for rel in _storefront_templates():
        if rel == "partials/empty_state.html":
            continue
        assert "empty-title" not in _template(rel), rel


def test_keys_feedback_faq_use_partial_with_actions():
    for rel, action in (
        ("keys.html", "Browse plans"),
        ("feedback.html", "Ask buyers in Discord"),
        ("faq.html", "Clear search"),
    ):
        src = _template(rel)
        assert 'include "partials/empty_state.html"' in src, rel
        assert action in src, rel


def test_skeletons_only_for_genuinely_async_content():
    for rel in _storefront_templates():
        if "skeleton" in _template(rel).lower():
            assert rel == "keys.html", rel
