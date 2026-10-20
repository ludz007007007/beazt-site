"""Forgot-password / reset flow + unified password rule (VAL-AUTH-001..005).

Route-level tests for:
- /auth/forgot (GET form, POST neutral confirmation for registered AND
  unregistered addresses, hash-only token storage, SMTP soft-fail)
- /auth/reset/<token> (valid reset, expiry rejected, single-use, tampered /
  never-issued tokens rejected, 8+ rule enforced)
- unified password validator shared by signup / reset / profile
- signup honoring ?next= (product-page return journey) + welcome flash
- login still honoring ?next= (regression guard while auth surface changes)
"""

from datetime import datetime, timedelta

import pytest


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _issue_reset_token(app, db, user, expires_at=None):
    """Create a token + its single-use row exactly like the forgot route."""
    from models import PasswordResetToken
    from utils.tokens import RESET_TOKEN_TTL, generate_reset_token, hash_token

    with app.app_context():
        token = generate_reset_token(user.id, expires_at=expires_at)
        db.session.add(PasswordResetToken(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=expires_at or datetime.utcnow() + RESET_TOKEN_TTL,
        ))
        db.session.commit()
    return token


# --------------------------------------------------------------------------
# /auth/forgot — request a reset (VAL-AUTH-003)
# --------------------------------------------------------------------------

class TestForgotRequest:
    def test_forgot_page_renders_form(self, client):
        resp = client.get("/auth/forgot")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'name="email"' in body
        assert "csrf_token" in body

    def test_login_page_links_forgot_password(self, client):
        body = client.get("/auth/login").get_data(as_text=True)
        assert 'href="/auth/forgot"' in body
        assert "Forgot password?" in body

    def test_registered_email_shows_confirmation(self, client, make_user, post_form):
        make_user("resetter", email="resetter@beazt.test")
        resp = post_form(client, "/auth/forgot", {"email": "resetter@beazt.test"})
        assert resp.status_code == 200
        assert "reset" in resp.get_data(as_text=True).lower()

    def test_unknown_email_same_confirmation_shape(self, client, db, make_user, post_form):
        """No account enumeration: registered and unknown emails must render
        an identical confirmation response."""
        make_user("resetter", email="resetter@beazt.test")
        known = post_form(client, "/auth/forgot", {"email": "resetter@beazt.test"})
        unknown = post_form(client, "/auth/forgot", {"email": "nobody@beazt.test"})
        assert known.status_code == unknown.status_code == 200
        assert known.get_data(as_text=True) == unknown.get_data(as_text=True)

    def test_no_error_flash_when_smtp_unconfigured(self, client, make_user, post_form):
        """SMTP is unconfigured in the test env — the confirmation state must
        still render softly (never an error page)."""
        make_user("resetter", email="resetter@beazt.test")
        resp = post_form(client, "/auth/forgot", {"email": "resetter@beazt.test"})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "flash-message" not in body  # no error toast on the confirmation

    def test_token_stored_as_hash_only(self, client, db, make_user, post_form):
        from models import PasswordResetToken

        make_user("resetter", email="resetter@beazt.test")
        post_form(client, "/auth/forgot", {"email": "resetter@beazt.test"})

        rows = PasswordResetToken.query.all()
        assert len(rows) == 1
        stored = rows[0].token_hash
        assert len(stored) == 64  # sha256 hex — never the raw token
        assert rows[0].used_at is None

    def test_reset_email_sent_when_mailer_available(
        self, client, db, make_user, post_form, monkeypatch
    ):
        sent = []

        def fake_send(to_address, subject, html_body, text_body=None):
            sent.append((to_address, subject, html_body, text_body))
            return True

        monkeypatch.setattr("utils.mailer.send_email", fake_send)
        make_user("resetter", email="resetter@beazt.test")
        post_form(client, "/auth/forgot", {"email": "resetter@beazt.test"})

        assert len(sent) == 1
        to, subject, html, text = sent[0]
        assert to == "resetter@beazt.test"
        assert "password" in subject.lower()
        assert "/auth/reset/" in html and "/auth/reset/" in (text or html)

    def test_authenticated_user_redirected(self, buyer_client):
        resp = buyer_client.get("/auth/forgot")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/my-keys")


# --------------------------------------------------------------------------
# /auth/reset/<token> — complete the reset (VAL-AUTH-004)
# --------------------------------------------------------------------------

class TestResetFlow:
    def test_valid_token_opens_reset_form(self, client, app, db, make_user):
        user = make_user("resetter", password="OldPass!234")
        token = _issue_reset_token(app, db, user)
        resp = client.get(f"/auth/reset/{token}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'name="password"' in body and 'name="confirm_password"' in body

    def test_reset_completes_and_new_password_logs_in(
        self, client, app, db, make_user, post_form, login
    ):
        user = make_user("resetter", password="OldPass!234")
        token = _issue_reset_token(app, db, user)

        resp = post_form(client, f"/auth/reset/{token}", {
            "password": "NewPass!5678",
            "confirm_password": "NewPass!5678",
        })
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

        db.session.refresh(user)
        assert user.check_password("NewPass!5678")
        assert not user.check_password("OldPass!234")

        assert login(client, "resetter", "NewPass!5678").status_code == 302

    def test_expired_token_rejected(self, client, app, db, make_user, post_form):
        user = make_user("resetter", password="OldPass!234")
        past = datetime.utcnow() - timedelta(minutes=5)
        token = _issue_reset_token(app, db, user, expires_at=past)

        get_resp = client.get(f"/auth/reset/{token}")
        assert get_resp.status_code == 400

        resp = post_form(client, f"/auth/reset/{token}", {
            "password": "NewPass!5678",
            "confirm_password": "NewPass!5678",
        })
        assert resp.status_code == 400
        db.session.refresh(user)
        assert user.check_password("OldPass!234")  # unchanged

    def test_token_single_use(self, client, app, db, make_user, post_form):
        user = make_user("resetter", password="OldPass!234")
        token = _issue_reset_token(app, db, user)

        first = post_form(client, f"/auth/reset/{token}", {
            "password": "NewPass!5678",
            "confirm_password": "NewPass!5678",
        })
        assert first.status_code == 302

        reuse_get = client.get(f"/auth/reset/{token}")
        assert reuse_get.status_code == 400

        reuse_post = post_form(client, f"/auth/reset/{token}", {
            "password": "Hacked!99999",
            "confirm_password": "Hacked!99999",
        })
        assert reuse_post.status_code == 400
        db.session.refresh(user)
        assert user.check_password("NewPass!5678")  # second use changed nothing

    def test_tampered_token_rejected(self, client, app, db, make_user):
        user = make_user("resetter", password="OldPass!234")
        token = _issue_reset_token(app, db, user)
        parts = token.split(".")
        parts[3] = ("0" if parts[3][0] != "0" else "1") + parts[3][1:]
        tampered = ".".join(parts)
        assert client.get(f"/auth/reset/{tampered}").status_code == 400

    def test_correctly_signed_but_never_issued_token_rejected(
        self, client, app, db, make_user
    ):
        """A token signed with our own key but without an issued single-use
        row (e.g. forged via a leaked signing oracle) is refused."""
        from utils.tokens import generate_reset_token

        user = make_user("resetter", password="OldPass!234")
        with app.app_context():
            token = generate_reset_token(user.id)
        assert client.get(f"/auth/reset/{token}").status_code == 400

    def test_reset_short_password_rejected(self, client, app, db, make_user, post_form):
        user = make_user("resetter", password="OldPass!234")
        token = _issue_reset_token(app, db, user)
        resp = post_form(client, f"/auth/reset/{token}", {
            "password": "short7",  # 7 chars — under the unified 8+ rule
            "confirm_password": "short7",
        })
        assert resp.status_code == 400
        assert "at least 8 characters" in resp.get_data(as_text=True)
        db.session.refresh(user)
        assert user.check_password("OldPass!234")

    def test_backup_everything_called_on_reset(
        self, client, app, db, make_user, post_form, monkeypatch
    ):
        """KV-restore safety contract: a password change must trigger
        backup_everything() (same as signup/profile)."""
        calls = []
        monkeypatch.setattr("utils.kv_store.backup_everything", lambda: calls.append(1))

        user = make_user("resetter", password="OldPass!234")
        token = _issue_reset_token(app, db, user)
        resp = post_form(client, f"/auth/reset/{token}", {
            "password": "NewPass!5678",
            "confirm_password": "NewPass!5678",
        })
        assert resp.status_code == 302
        assert len(calls) == 1

    def test_authenticated_user_redirected(self, buyer_client, app, db, make_user):
        from utils.tokens import generate_reset_token

        user = make_user("resetter", password="OldPass!234")
        with app.app_context():
            token = generate_reset_token(user.id)
        resp = buyer_client.get(f"/auth/reset/{token}")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/my-keys")


# --------------------------------------------------------------------------
# Unified 8+ password rule (VAL-AUTH-002 / VAL-ACC-005)
# --------------------------------------------------------------------------

class TestUnifiedPasswordRule:
    def test_signup_rejects_seven_char_password(self, client, db, post_form):
        from models import User

        resp = post_form(client, "/auth/signup", {
            "username": "shorty",
            "email": "shorty@beazt.test",
            "password": "short7",
            "confirm_password": "short7",
        })
        assert resp.status_code == 200  # re-renders with errors
        assert "at least 8 characters" in resp.get_data(as_text=True)
        assert User.query.filter_by(username="shorty").first() is None

    def test_profile_rejects_short_new_password(self, buyer_client, db, post_form):
        from models import User

        user = User.query.filter_by(username="buyer").first()
        resp = post_form(buyer_client, "/profile", {
            "email": user.email,
            "current_password": "password123",
            "new_password": "short7",
            "confirm_password": "short7",
        }, follow_redirects=True)
        assert "at least 8 characters" in resp.get_data(as_text=True)
        db.session.refresh(user)
        assert user.check_password("password123")  # unchanged


# --------------------------------------------------------------------------
# Signup return journey + welcome flash (VAL-AUTH-002, VAL-CROSS-001)
# --------------------------------------------------------------------------

class TestSignupNextJourney:
    def test_signup_with_next_redirects_to_next(self, client, db, post_form):
        resp = post_form(client, "/auth/signup?next=/cheats", {
            "username": "newbuyer",
            "email": "newbuyer@beazt.test",
            "password": "ValidPass!1",
            "confirm_password": "ValidPass!1",
        })
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/cheats")

    def test_signup_without_next_redirects_to_my_keys(self, client, db, post_form):
        resp = post_form(client, "/auth/signup", {
            "username": "newbuyer",
            "email": "newbuyer@beazt.test",
            "password": "ValidPass!1",
            "confirm_password": "ValidPass!1",
        })
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/my-keys")

    def test_signup_ignores_unsafe_next(self, client, db, post_form):
        resp = post_form(client, "/auth/signup?next=https://evil.example", {
            "username": "newbuyer",
            "email": "newbuyer@beazt.test",
            "password": "ValidPass!1",
            "confirm_password": "ValidPass!1",
        })
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/my-keys")

    def test_signup_shows_welcome_flash(self, client, db, post_form):
        resp = post_form(client, "/auth/signup", {
            "username": "newbuyer",
            "email": "newbuyer@beazt.test",
            "password": "ValidPass!1",
            "confirm_password": "ValidPass!1",
        }, follow_redirects=True)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "welcome" in body.lower()
        assert "flash" in body.lower() or "toast" in body.lower()


# --------------------------------------------------------------------------
# Regression: login return journey stays intact (VAL-AUTH-001)
# --------------------------------------------------------------------------

class TestLoginNextRegression:
    def test_login_with_next_lands_on_target(self, client, db, make_user, post_form):
        make_user("returner", password="password123")
        resp = post_form(client, "/auth/login?next=/status", {
            "username": "returner",
            "password": "password123",
        })
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/status")

    def test_login_invalid_credentials_inline_error(self, client, db, post_form):
        resp = post_form(client, "/auth/login", {
            "username": "ghost",
            "password": "wrongpass1",
        })
        assert resp.status_code == 200
        assert "Invalid username or password" in resp.get_data(as_text=True)


# --------------------------------------------------------------------------
# Copy canon: "Operator" jargon retired from auth titles (VAL-CON-005)
# --------------------------------------------------------------------------

class TestAuthTitles:
    def test_login_title_has_no_operator_jargon(self, client):
        body = client.get("/auth/login").get_data(as_text=True)
        assert "<title>Sign in | BEAZT</title>" in body

    def test_signup_title_has_no_operator_jargon(self, client):
        body = client.get("/auth/signup").get_data(as_text=True)
        assert "<title>Create account | BEAZT</title>" in body
