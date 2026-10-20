"""Shared pytest fixtures for the BEAZT Flask app.

`app.py` configures itself at import time (DB URI, migrations, seeding), so
the isolation env vars below MUST be set before anything imports `app`,
`config`, or `models`. Each test gets a freshly dropped/recreated schema in a
throwaway SQLite file; the developer database in instance/ is never touched.
"""

import os
import secrets
import shutil
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_TMP_DIR = tempfile.mkdtemp(prefix="beazt-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP_DIR, "test.db").replace("\\", "/")
# kv_store restores products/users from $TMPDIR/*.json file backups at import;
# point it at the empty temp dir so stray backups never leak into tests.
os.environ["TMPDIR"] = _TMP_DIR
os.environ["KV_URL"] = ""
os.environ["REDIS_URL"] = ""
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ADMIN_EMAIL"] = "admin@beazt.test"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
# Synthetic IVNO webhook secret (mirrors .env) — must be set before app/config
# import so get_ivno_config() picks it up as the env fallback.
os.environ["IVNO_WEBHOOK_SECRET"] = "ivno_test_synthetic_webhook_secret_local"


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def app():
    from app import app as flask_app

    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def db(app):
    """Clean schema per test; yields the Flask-SQLAlchemy handle."""
    from models import db as _db

    with app.app_context():
        _db.session.remove()
        _db.drop_all()
        _db.create_all()
        yield _db
        _db.session.remove()


@pytest.fixture
def client(app, db):
    return app.test_client()


def _ensure_csrf_token(client):
    with client.session_transaction() as sess:
        token = sess.get("_csrf_token")
        if not token:
            token = secrets.token_hex(32)
            sess["_csrf_token"] = token
    return token


@pytest.fixture
def csrf_token():
    """Return a callable: csrf_token(client) -> token stored in that client's session."""
    return _ensure_csrf_token


@pytest.fixture
def post_form(csrf_token):
    """POST form data with a valid CSRF token: post_form(client, url, data=None, **kw)."""

    def _post(client, url, data=None, **kwargs):
        payload = dict(data or {})
        payload.setdefault("csrf_token", csrf_token(client))
        return client.post(url, data=payload, **kwargs)

    return _post


@pytest.fixture
def make_user(db):
    """Factory: make_user(username, password="password123", is_admin=False, email=None)."""
    from models import User

    def _make(username, password="password123", is_admin=False, email=None, is_active=True):
        user = User(
            username=username,
            email=email or f"{username}@beazt.test",
            is_admin=is_admin,
            is_active=is_active,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    return _make


@pytest.fixture
def make_product(db):
    """Factory: make_product(slug, tiers=[(label, days, price_pence, is_subscription)], **fields)."""
    from models import PricingTier, Product

    def _make(slug="test-product", name=None, tiers=None, **fields):
        fields.setdefault("key_source", "pool")
        fields.setdefault("status", "undetected")
        product = Product(name=name or slug.replace("-", " ").title(), slug=slug, **fields)
        db.session.add(product)
        db.session.flush()
        for label, days, price, is_sub in tiers or [("1 Day", 1, 900, False)]:
            db.session.add(PricingTier(
                product_id=product.id,
                label=label,
                duration_days=days,
                price_pence=price,
                is_subscription=is_sub,
                billing_type="subscription" if is_sub else "one_time",
            ))
        db.session.commit()
        return product

    return _make


@pytest.fixture
def login(post_form):
    """login(client, username, password) -> response of POST /auth/login (not followed)."""

    def _login(client, username, password="password123"):
        return post_form(client, "/auth/login", {"username": username, "password": password})

    return _login


@pytest.fixture
def buyer_client(client, make_user, login):
    make_user("buyer", "password123")
    resp = login(client, "buyer", "password123")
    assert resp.status_code == 302, resp.data[:300]
    return client


@pytest.fixture
def admin_client(client, make_user, login):
    make_user("tester_admin", "password123", is_admin=True)
    resp = login(client, "tester_admin", "password123")
    assert resp.status_code == 302, resp.data[:300]
    return client
