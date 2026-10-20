"""Profile page (VAL-ACC-005): shared form system + inline field errors.

Route-level tests for /profile:
- per-field server validation: failures re-render the form with field-keyed
  inline errors in the field's own slot (role=alert, aria-invalid), never a
  bare flash-and-redirect
- current password required for ANY change (email or password)
- unified 8+ password rule (shared validator with signup/reset)
- email + password changes persist, backup_everything() preserved
- client-side rule parity: script.js covers new_password and form-scoped
  confirm matching (same message as signup)
"""

import re

from utils.passwords import password_error


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _error_slot(html, field_id):
    """Return (visible, text) for a profile field's inline error slot.

    The slot is the div ``id="<field_id>-error"``; the server renders it
    WITHOUT the hidden attribute when the field failed validation.
    """
    m = re.search(
        r'<div class="form-error" id="' + field_id + r'-error" role="alert" data-error-slot( hidden)?>(.*?)</div>',
        html, re.S)
    if not m:
        return None
    text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
    return m.group(1) is None, text


def _input_marked_invalid(html, field_id):
    return bool(re.search(
        r'<input[^>]*id="' + field_id + r'"[^>]*aria-invalid="true"', html))


# --------------------------------------------------------------------------
# Form system baseline (shared markup, zero inline styles)
# --------------------------------------------------------------------------

class TestProfileFormSystem:
    def test_profile_renders_on_the_form_system(self, buyer_client):
        html = buyer_client.get("/profile").get_data(as_text=True)
        for marker in ("form-group", "form-label", "form-input", 'role="alert"'):
            assert marker in html, marker
        # Clean GET renders every error slot hidden — no stale errors.
        for field_id in ("profile-email", "profile-current-password",
                         "profile-new-password", "profile-confirm-password"):
            slot = _error_slot(html, field_id)
            assert slot is not None and slot[0] is False, field_id
        assert "style=" not in html

    def test_password_fields_have_toggles_and_autocomplete(self, buyer_client):
        html = buyer_client.get("/profile").get_data(as_text=True)
        assert 'autocomplete="current-password"' in html
        assert html.count('autocomplete="new-password"') >= 2
        # Visibility toggles on every password field (auth-form parity).
        assert html.count('class="password-toggle"') == 3
        assert "Show password" in html

    def test_get_passes_no_field_errors(self, buyer_client):
        html = buyer_client.get("/profile").get_data(as_text=True)
        assert "is-error" not in html
        assert 'aria-invalid="true"' not in html


# --------------------------------------------------------------------------
# Per-field server validation (inline errors, not flash redirects)
# --------------------------------------------------------------------------

class TestInlineFieldErrors:
    def test_wrong_current_password_inline_field_error(self, buyer_client, db, post_form):
        from models import User

        user = User.query.filter_by(username="buyer").first()
        resp = post_form(buyer_client, "/profile", {
            "email": user.email,
            "current_password": "totally-wrong",
            "new_password": "NewValidPass!42",
            "confirm_password": "NewValidPass!42",
        })
        assert resp.status_code == 200  # re-renders with errors
        html = resp.get_data(as_text=True)
        visible, text = _error_slot(html, "profile-current-password")
        assert visible
        assert text == "Current password is incorrect."
        assert _input_marked_invalid(html, "profile-current-password")
        # No error flash toast for a field-level problem.
        assert "flash-message flash-error" not in html
        db.session.refresh(user)
        assert user.check_password("password123")  # unchanged

    def test_short_new_password_matches_signup_rule(self, buyer_client, db, post_form):
        from models import User

        user = User.query.filter_by(username="buyer").first()
        resp = post_form(buyer_client, "/profile", {
            "email": user.email,
            "current_password": "password123",
            "new_password": "short7",
            "confirm_password": "short7",
        })
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        visible, text = _error_slot(html, "profile-new-password")
        assert visible
        # Exact same copy as the shared validator (signup/reset use it too).
        assert text == password_error("short7")
        assert text == "Password must be at least 8 characters."
        assert _input_marked_invalid(html, "profile-new-password")
        db.session.refresh(user)
        assert user.check_password("password123")

    def test_missing_current_password_blocks_change(self, buyer_client, db, post_form):
        from models import User

        user = User.query.filter_by(username="buyer").first()
        resp = post_form(buyer_client, "/profile", {
            "email": "renamed@beazt.test",  # email change without password
        })
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        visible, text = _error_slot(html, "profile-current-password")
        assert visible
        assert text == "Enter your current password to save changes."
        db.session.refresh(user)
        assert user.email == "buyer@beazt.test"  # unchanged

    def test_wrong_current_password_blocks_email_change(self, buyer_client, db, post_form):
        from models import User

        user = User.query.filter_by(username="buyer").first()
        resp = post_form(buyer_client, "/profile", {
            "email": "renamed@beazt.test",
            "current_password": "nope-wrong",
        })
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        visible, _ = _error_slot(html, "profile-current-password")
        assert visible
        db.session.refresh(user)
        assert user.email == "buyer@beazt.test"

    def test_mismatched_confirm_inline_field_error(self, buyer_client, db, post_form):
        from models import User

        user = User.query.filter_by(username="buyer").first()
        resp = post_form(buyer_client, "/profile", {
            "email": user.email,
            "current_password": "password123",
            "new_password": "NewValidPass!42",
            "confirm_password": "DifferentPass!9",
        })
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        visible, text = _error_slot(html, "profile-confirm-password")
        assert visible
        assert text == "New passwords do not match."
        db.session.refresh(user)
        assert user.check_password("password123")

    def test_email_in_use_inline_field_error(self, buyer_client, db, make_user, post_form):
        from models import User

        make_user("squatter", email="taken@beazt.test")
        user = User.query.filter_by(username="buyer").first()
        resp = post_form(buyer_client, "/profile", {
            "email": "taken@beazt.test",
            "current_password": "password123",
        })
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        visible, text = _error_slot(html, "profile-email")
        assert visible
        assert text == "Email already in use."
        assert _input_marked_invalid(html, "profile-email")
        db.session.refresh(user)
        assert user.email == "buyer@beazt.test"

    def test_invalid_email_format_inline_field_error(self, buyer_client, post_form):
        resp = post_form(buyer_client, "/profile", {
            "email": "not-an-email",
            "current_password": "password123",
        })
        assert resp.status_code == 200
        visible, text = _error_slot(resp.get_data(as_text=True), "profile-email")
        assert visible
        assert text == "Please enter a valid email address."

    def test_multiple_field_errors_render_together(self, buyer_client, post_form):
        """Per-field validation: every failing field shows its own error in
        one pass (wrong current password AND short new password)."""
        resp = post_form(buyer_client, "/profile", {
            "email": "buyer@beazt.test",
            "current_password": "wrong",
            "new_password": "short7",
            "confirm_password": "unrelated",
        })
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        for field_id, message in (
            ("profile-current-password", "Current password is incorrect."),
            ("profile-new-password", "Password must be at least 8 characters."),
            ("profile-confirm-password", "New passwords do not match."),
        ):
            visible, text = _error_slot(html, field_id)
            assert visible, field_id
            assert text == message, field_id

    def test_submitted_email_preserved_on_error(self, buyer_client, post_form):
        resp = post_form(buyer_client, "/profile", {
            "email": "kept@beazt.test",
            "current_password": "wrong",
        })
        html = resp.get_data(as_text=True)
        assert 'value="kept@beazt.test"' in html


# --------------------------------------------------------------------------
# Successful changes persist (+ KV backup contract)
# --------------------------------------------------------------------------

class TestSuccessfulChanges:
    def test_email_change_persists_with_correct_password(
        self, buyer_client, db, post_form, monkeypatch
    ):
        from models import User

        calls = []
        monkeypatch.setattr("utils.kv_store.backup_everything", lambda: calls.append(1))
        user = User.query.filter_by(username="buyer").first()
        resp = post_form(buyer_client, "/profile", {
            "email": "renamed@beazt.test",
            "current_password": "password123",
        })
        assert resp.status_code == 302
        db.session.refresh(user)
        assert user.email == "renamed@beazt.test"
        assert len(calls) == 1  # KV restore safety preserved

    def test_password_change_persists(
        self, buyer_client, db, post_form, monkeypatch
    ):
        from models import User

        calls = []
        monkeypatch.setattr("utils.kv_store.backup_everything", lambda: calls.append(1))
        user = User.query.filter_by(username="buyer").first()
        resp = post_form(buyer_client, "/profile", {
            "email": user.email,
            "current_password": "password123",
            "new_password": "BrandNewPass!7",
            "confirm_password": "BrandNewPass!7",
        })
        assert resp.status_code == 302
        db.session.refresh(user)
        assert user.check_password("BrandNewPass!7")
        assert len(calls) == 1

    def test_email_and_password_change_together(self, buyer_client, db, post_form):
        from models import User

        user = User.query.filter_by(username="buyer").first()
        resp = post_form(buyer_client, "/profile", {
            "email": "both@beazt.test",
            "current_password": "password123",
            "new_password": "BrandNewPass!7",
            "confirm_password": "BrandNewPass!7",
        })
        assert resp.status_code == 302
        db.session.refresh(user)
        assert user.email == "both@beazt.test"
        assert user.check_password("BrandNewPass!7")

    def test_no_change_submission_still_succeeds(self, buyer_client, post_form):
        """Same email, no password fields: nothing to confirm — success
        redirect (keeps the auto-dismiss success toast contract)."""
        resp = post_form(buyer_client, "/profile", {"email": "buyer@beazt.test"},
                         follow_redirects=True)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "flash-message flash-success" in html


# --------------------------------------------------------------------------
# Client-side rule parity (script.js)
# --------------------------------------------------------------------------

class TestClientRuleParity:
    def test_script_covers_new_password_with_signup_rule(self):
        with open("static/js/script.js", encoding="utf-8") as fh:
            js = fh.read()
        # The 8+ rule fires for new_password (profile), not just password.
        assert 'name === "password" || name === "new_password"' in js
        # Confirm matching is scoped to the same form and knows new_password.
        assert "input[name=\"password\"], input[name=\"new_password\"]" in js

    def test_script_focuses_first_server_rendered_error(self):
        with open("static/js/script.js", encoding="utf-8") as fh:
            js = fh.read()
        assert "focusFirstServerError" in js
