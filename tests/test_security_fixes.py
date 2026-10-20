"""Security-critical fixes: IVNO webhook auth, admin seed, health gating,
login `next` sanitization, checkout quantity validation, session hardening.

Covers VAL-SEC-001..003, VAL-CHECKOUT-002/010/011, VAL-AUTH-004 (next).
"""

import os

import pytest

from models import Key, Order, PricingTier, User

IVNO_SECRET = os.environ["IVNO_WEBHOOK_SECRET"]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- helpers ---------------------------------------------------------------

def _csrf_of(client):
    """Read (creating if needed) the CSRF token from the client's session."""
    import secrets as _secrets
    with client.session_transaction() as sess:
        token = sess.get("_csrf_token")
        if not token:
            token = _secrets.token_hex(32)
            sess["_csrf_token"] = token
    return token


def _seed_pool_order(db, make_user, make_product, slug="sec-prod"):
    user = make_user("sec_buyer")
    product = make_product(slug, tiers=[("1 Day", 1, 900, False)])
    tier = PricingTier.query.filter_by(product_id=product.id).first()
    db.session.add(Key(user_id=None, product_id=product.id, tier_id=tier.id,
                       key_value="POOLKEY-SEC-1", is_active=False))
    order = Order(user_id=user.id, tier_id=tier.id, status="pending", quantity=1)
    db.session.add(order)
    db.session.commit()
    return user, product, tier, order


def _webhook_payload(order):
    return {"event": "payment.completed", "status": "completed",
            "order_id": f"BEAZT-{order.id}"}


# --- IVNO webhook auth (VAL-CHECKOUT-010 / 011) ----------------------------

def test_ivno_webhook_unsigned_rejected_403(client, db, make_user, make_product):
    _, _, _, order = _seed_pool_order(db, make_user, make_product)
    resp = client.post("/checkout/ivno-webhook", json=_webhook_payload(order))
    assert resp.status_code == 403
    db.session.refresh(order)
    assert order.status == "pending"


def test_ivno_webhook_wrong_secret_rejected_403(client, db, make_user, make_product):
    _, _, _, order = _seed_pool_order(db, make_user, make_product, "sec-prod2")
    resp = client.post("/checkout/ivno-webhook", json=_webhook_payload(order),
                       headers={"X-Webhook-Secret": "wrong-secret"})
    assert resp.status_code == 403
    db.session.refresh(order)
    assert order.status == "pending"
    assert Key.query.filter_by(order_id=order.id).count() == 0


def test_ivno_webhook_invalid_hmac_rejected_403(client, db, make_user, make_product):
    import hashlib
    import hmac as hmac_mod
    _, _, _, order = _seed_pool_order(db, make_user, make_product, "sec-prod3")
    raw = client.application.json.dumps(_webhook_payload(order)).encode()
    bad_sig = hashlib.sha256(raw).hexdigest()  # not an HMAC of the secret
    assert not hmac_mod.compare_digest(bad_sig, hmac_mod.new(
        IVNO_SECRET.encode(), raw, hashlib.sha256).hexdigest())
    resp = client.post("/checkout/ivno-webhook", data=raw,
                       content_type="application/json",
                       headers={"X-Webhook-Signature": bad_sig})
    assert resp.status_code == 403
    db.session.refresh(order)
    assert order.status == "pending"


def test_ivno_webhook_valid_secret_fulfills(client, db, make_user, make_product):
    user, _, _, order = _seed_pool_order(db, make_user, make_product, "sec-prod4")
    resp = client.post("/checkout/ivno-webhook", json=_webhook_payload(order),
                       headers={"X-Webhook-Secret": IVNO_SECRET})
    assert resp.status_code == 200
    db.session.refresh(order)
    assert order.status == "completed"
    keys = Key.query.filter_by(order_id=order.id).all()
    assert len(keys) == 1
    assert keys[0].user_id == user.id
    assert keys[0].is_active


def test_ivno_webhook_valid_hmac_fulfills(client, db, make_user, make_product):
    import hashlib
    import hmac as hmac_mod
    _, _, _, order = _seed_pool_order(db, make_user, make_product, "sec-prod5")
    raw = client.application.json.dumps(_webhook_payload(order)).encode()
    sig = hmac_mod.new(IVNO_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    resp = client.post("/checkout/ivno-webhook", data=raw,
                       content_type="application/json",
                       headers={"X-Webhook-Signature": sig})
    assert resp.status_code == 200
    db.session.refresh(order)
    assert order.status == "completed"


def test_ivno_webhook_replay_idempotent(client, db, make_user, make_product):
    _, _, _, order = _seed_pool_order(db, make_user, make_product, "sec-prod6")
    headers = {"X-Webhook-Secret": IVNO_SECRET}
    first = client.post("/checkout/ivno-webhook", json=_webhook_payload(order), headers=headers)
    assert first.status_code == 200
    assert Key.query.filter_by(order_id=order.id).count() == 1
    second = client.post("/checkout/ivno-webhook", json=_webhook_payload(order), headers=headers)
    assert second.status_code == 200
    assert Key.query.filter_by(order_id=order.id).count() == 1
    db.session.refresh(order)
    assert order.status == "completed"


def test_ivno_webhook_non_ascii_signature_rejected_403(client, db, make_user, make_product):
    """Non-ASCII X-Webhook-Signature must yield 403, never a TypeError 500."""
    _, _, _, order = _seed_pool_order(db, make_user, make_product, "sec-prod7")
    resp = client.post("/checkout/ivno-webhook", json=_webhook_payload(order),
                       headers={"X-Webhook-Signature": "недействительный-подпись"})
    assert resp.status_code == 403
    db.session.refresh(order)
    assert order.status == "pending"
    assert Key.query.filter_by(order_id=order.id).count() == 0


def test_ivno_webhook_non_ascii_secret_rejected_403(client, db, make_user, make_product):
    """Non-ASCII X-Webhook-Secret must yield 403, never a TypeError 500."""
    _, _, _, order = _seed_pool_order(db, make_user, make_product, "sec-prod8")
    resp = client.post("/checkout/ivno-webhook", json=_webhook_payload(order),
                       headers={"X-Webhook-Secret": "секрет-неверный"})
    assert resp.status_code == 403
    db.session.refresh(order)
    assert order.status == "pending"


def test_ivno_webhook_unknown_order_not_fulfilled(client, db, make_user, make_product):
    resp = client.post("/checkout/ivno-webhook",
                       json={"status": "completed", "order_id": "BEAZT-99999"},
                       headers={"X-Webhook-Secret": IVNO_SECRET})
    assert resp.status_code == 200  # acknowledged, no fulfillment possible
    assert Order.query.count() == 0


# --- Admin seed guard (VAL-SEC-002) ----------------------------------------

def test_seed_admin_env_unset_creates_no_admin(db, monkeypatch, capsys):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    from models import seed_admin
    seed_admin()
    assert User.query.filter_by(is_admin=True).count() == 0
    out = capsys.readouterr().out
    assert "ADMIN_EMAIL" in out or "ADMIN_PASSWORD" in out  # first-run warning


def test_seed_admin_env_set_creates_admin(db, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "SuperSecretPass123")
    from models import seed_admin
    seed_admin()
    admin = User.query.filter_by(username="admin").one()
    assert admin.is_admin
    assert admin.check_password("SuperSecretPass123")


BANNED_STRINGS = ("58394Ludz", "ludwig.streso@gmail.com")


def test_no_hardcoded_admin_credentials_in_source():
    scan_dirs = []
    for name in ("models.py", "app.py", "config.py", "README.md"):
        scan_dirs.append(os.path.join(REPO_ROOT, name))
    for sub in ("routes", "templates", "scripts", "docs", "utils"):
        scan_dirs.append(os.path.join(REPO_ROOT, sub))
    offenders = []
    for entry in scan_dirs:
        if os.path.isfile(entry):
            files = [entry]
        elif os.path.isdir(entry):
            files = [os.path.join(dp, f) for dp, _, fs in os.walk(entry) for f in fs
                     if f.endswith((".py", ".html", ".md"))]
        else:
            continue
        for path in files:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            for banned in BANNED_STRINGS:
                if banned in content:
                    offenders.append((path, banned))
    assert offenders == []


# --- Health endpoint gating (VAL-SEC-001) -----------------------------------

def _clear_user_cache():
    """Drop flask-login's ``g._login_user`` cache.

    The ``db`` fixture keeps an app context open for the whole test, and this
    Flask version reuses the active app context for test requests, so the
    cached current_user would otherwise leak between separate test clients.
    """
    from flask import g
    g.pop("_login_user", None)


@pytest.mark.parametrize("path", ["/health/products", "/health/kv"])
def test_health_endpoints_require_admin(app, db, make_user, login, path):
    anon = app.test_client()
    resp = anon.get(path)
    assert resp.status_code in (301, 302), (path, resp.status_code)
    assert "/auth/login" in resp.headers.get("Location", "")

    _clear_user_cache()
    make_user("h_buyer", is_admin=False)
    buyer = app.test_client()
    assert login(buyer, "h_buyer").status_code == 302
    denied = buyer.get(path)
    assert denied.status_code == 403, (path, denied.status_code)

    _clear_user_cache()
    make_user("h_admin", is_admin=True)
    admin = app.test_client()
    assert login(admin, "h_admin").status_code == 302
    allowed = admin.get(path)
    assert allowed.status_code == 200, allowed.get_data(as_text=True)[:300]


def test_health_kv_anon_body_has_no_env_values(app, db):
    anon = app.test_client()
    resp = anon.get("/health/kv")
    assert resp.status_code in (301, 302)
    body = resp.get_data(as_text=True)
    assert "ivno_test_synthetic" not in body
    assert "KV_REST" not in body
    assert "UPSTASH" not in body.upper() or resp.status_code != 200


# --- Login `next` sanitization (VAL-AUTH-004 / VAL-CROSS-003) ---------------

def _login_with_next(client, post_form, next_value):
    return post_form(client, f"/auth/login?next={next_value}",
                     {"username": "buyer", "password": "password123"})


def test_login_malicious_next_ignored(client, make_user, post_form):
    make_user("buyer")
    for bad in ("//evil.com", "https://evil.com", "http://evil.com/x",
                "\\\\evil.com", "javascript:alert(1)"):
        resp = _login_with_next(client, post_form, bad.replace("\\", "%5C")
                                if "\\" in bad else bad)
        assert resp.status_code == 302
        loc = resp.headers.get("Location", "")
        assert "evil.com" not in loc and "javascript" not in loc, (bad, loc)


def test_login_valid_relative_next_followed(client, make_user, post_form):
    make_user("buyer")
    resp = _login_with_next(client, post_form, "%2Fcheats")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/cheats")


# --- Checkout quantity validation (VAL-CHECKOUT-002) ------------------------

@pytest.mark.parametrize("qty", ["abc", "0", "-3", "11", "999", "1e5",
                                 "Infinity", "inf", "1e999", "nan"])
def test_checkout_quantity_rejected_friendly(buyer_client, make_product, qty):
    product = make_product("qty-prod", tiers=[("30 Days", 30, 4900, False)])
    tier = PricingTier.query.filter_by(product_id=product.id).first()
    resp = buyer_client.post("/checkout/create-session",
                             data={"tier_id": tier.id, "quantity": qty,
                                   "csrf_token": _csrf_of(buyer_client)})
    assert resp.status_code != 500
    assert resp.status_code == 400
    assert "error" in resp.get_json()
    assert "1" in resp.get_json()["error"] and "10" in resp.get_json()["error"]


def test_checkout_quantity_valid_creates_order(buyer_client, make_product):
    product = make_product("qty-prod-ok", tiers=[("30 Days", 30, 4900, False)])
    tier = PricingTier.query.filter_by(product_id=product.id).first()
    before = Order.query.count()
    resp = buyer_client.post("/checkout/create-session",
                             data={"tier_id": str(tier.id), "quantity": "2",
                                   "csrf_token": _csrf_of(buyer_client)})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert Order.query.count() == before + 1


def test_checkout_garbage_tier_id_no_500(buyer_client):
    resp = buyer_client.post("/checkout/create-session",
                             data={"tier_id": "abc", "quantity": "1",
                                   "csrf_token": _csrf_of(buyer_client)})
    assert resp.status_code == 400


# --- CSRF / session hardening (VAL-SEC-003) ---------------------------------

def test_checkout_post_requires_csrf(client, db, make_user, make_product, post_form):
    make_user("nocsrf")
    product = make_product("csrf-prod", tiers=[("1 Day", 1, 900, False)])
    tier = PricingTier.query.filter_by(product_id=product.id).first()
    # Establish a real session through the CSRF-guarded login helper...
    resp = post_form(client, "/auth/login",
                     {"username": "nocsrf", "password": "password123"})
    assert resp.status_code == 302
    resp = client.post("/checkout/create-session",
                       data={"tier_id": str(tier.id), "quantity": "1"})
    assert resp.status_code in (400, 403)
    assert Order.query.count() == 0


def test_session_cookie_flags(client, make_user, post_form):
    make_user("cookietester")
    resp = post_form(client, "/auth/login",
                     {"username": "cookietester", "password": "password123"})
    assert resp.status_code == 302
    set_cookies = resp.headers.getlist("Set-Cookie")
    assert set_cookies, "no session cookie set"
    joined = "; ".join(set_cookies)
    assert "HttpOnly" in joined
    assert "SameSite=Lax" in joined
