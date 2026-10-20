"""Regression tests for VAL-AUTH-005: focus must move to the first inline
error after a SERVER-rendered failed login.

Root cause (m3 user-testing r1, reproduced twice): script.js calls
focusFirstServerError() on DOMContentLoaded, but auth-form.js
mapServerFlashes() — which injects the .is-error[aria-invalid=true] state
from the flashed error — runs afterwards (script.js loads first in
base.html), so the focus query found nothing. Client-side invalid submits
already focused correctly; only the server-rendered path was broken.

The fix: script.js exposes focusFirstServerError on window.BEAZT, and
auth-form.js re-runs it after mapServerFlashes() injects the inline errors.
"""

import re


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------
# Server-rendered failed login: the page the browser fix operates on
# --------------------------------------------------------------------------
class TestFailedLoginRender:
    def test_failed_login_re_renders_form_with_error_flash(self, client, make_user, post_form):
        make_user("realuser", password="CorrectHorse1")
        resp = post_form(client, "/auth/login", {"username": "realuser", "password": "wrong-pass"})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Invalid username or password." in body
        # The error flash toast is what auth-form.js re-routes into the
        # inline username slot (then re-focuses).
        assert re.search(r'class="flash-container"', body)
        assert 'data-flash-kind="error"' in body

    def test_login_template_wires_error_slots(self, client):
        body = client.get("/auth/login").get_data(as_text=True)
        assert 'id="username"' in body
        assert 'data-error-id="username-error"' in body
        assert 'id="username-error"' in body
        assert 'role="alert"' in body


# --------------------------------------------------------------------------
# Focus wiring (source-scan: the browser race is not observable from the
# Flask test client)
# --------------------------------------------------------------------------
class TestFocusWiring:
    def test_script_exposes_focus_first_server_error(self):
        js = _read("static/js/script.js")
        assert "function focusFirstServerError" in js
        # Exposed on the shared BEAZT namespace so auth-form.js (executed
        # after script.js) can re-run it once server flashes are mapped.
        assert re.search(
            r"window\.BEAZT\.focusFirstServerError\s*=\s*focusFirstServerError", js
        )

    def test_auth_form_reruns_focus_after_mapping_server_flashes(self):
        js = _read("static/js/auth-form.js")
        mapped = js.index("mapServerFlashes();")
        refocus = js.index("window.BEAZT.focusFirstServerError();")
        assert mapped < refocus, (
            "focus must run AFTER mapServerFlashes() injects the error state "
            "(VAL-AUTH-005: the DOMContentLoaded call in script.js runs first "
            "and finds no errors yet)"
        )

    def test_cache_busters_bumped(self, client):
        body = client.get("/auth/login").get_data(as_text=True)
        assert "/static/js/script.js?v=19" in body
        assert "/static/js/auth-form.js?v=3" in body
        for name in ("login.html", "signup.html", "forgot.html", "reset.html"):
            assert 'auth-form.js?v=3' in _read(f"templates/{name}"), name
        assert "script.js?v=19" in _read("templates/admin/base.html")
