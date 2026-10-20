"""Route-level tests for the /my-keys rebuild (m3-my-keys).

Covers the validation-contract assertions owned by this feature:
- VAL-ACC-001  dashboard content is server-rendered (no x-cloak gating, no
               artificial hydration delay)
- VAL-ACC-002  masked-by-default key values with accurate expiry math
- VAL-ACC-003  Active / Expired / Revoked are distinct, renewal CTA targets
               the product page, loader download gated to active keys
- VAL-ACC-004  buyer-facing order history lists completed orders only
- VAL-ACC-006  status filter chips (All / Active / Expired)
- VAL-CROSS-003 fresh-account empty state with a catalogue CTA
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from models import Key, Order

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "keys.html"


def _make_key(db, user, product, tier, value, *, is_active=True, expires_at=None,
              assigned_at=None, chairfbi_key_id=None):
    key = Key(
        user_id=user.id, product_id=product.id, tier_id=tier.id,
        key_value=value, is_active=is_active, expires_at=expires_at,
        assigned_at=assigned_at, chairfbi_key_id=chairfbi_key_id,
    )
    db.session.add(key)
    db.session.commit()
    return key


def _make_order(db, user, tier, *, session_id, status="completed", qty=1, days_ago=0):
    order = Order(
        user_id=user.id, tier_id=tier.id, status=status, quantity=qty,
        stripe_session_id=session_id,
        created_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    db.session.add(order)
    db.session.commit()
    return order


def _card(html, state):
    """Return the rendered markup chunk of the one key card in `state`."""
    start = html.index(f'data-key-state="{state}"')
    nxt = html.find('data-key-state="', start + 10)
    return html[start:nxt if nxt != -1 else len(html)]


@pytest.fixture
def buyer(client, db, make_user, login, make_product):
    """Logged-in buyer `keybuyer` plus a two-tier product."""
    user = make_user("keybuyer")
    assert login(client, "keybuyer").status_code == 302
    product = make_product(
        "rust-esp-lite", name="Rust ESP Lite",
        tiers=[("1 Day", 1, 900, False), ("1 Month", 30, 4900, False)])
    return user, product


# ---------------------------------------------------------------------------
# Access + server-rendered dashboard (VAL-ACC-001)
# ---------------------------------------------------------------------------

def test_my_keys_requires_login(client):
    resp = client.get("/my-keys")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_key_cards_render_in_server_html(client, db, buyer):
    user, product = buyer
    tier = product.tiers.all()[1]
    _make_key(db, user, product, tier, "BEAZT-AAAA-1111",
              expires_at=datetime.utcnow() + timedelta(days=16))
    html = client.get("/my-keys").data.decode()

    assert 'data-key-state="active"' in html
    assert "Rust ESP Lite" in html
    # Masked by default: prefix + bullets + suffix, never the bare value.
    assert "BEAZZ" not in html
    assert "BEAZ" + "•" * 7 + "1111" in html


def test_template_never_x_cloaks_real_content_or_delays_hydration():
    src = TEMPLATE.read_text(encoding="utf-8")

    # The dashboard content wrapper must not hide behind x-cloak: no-JS
    # visitors see the server-rendered page (VAL-ACC-001).
    wrapper = re.search(r'<div class="keys-content"[^>]*>', src)
    assert wrapper, "keys-content wrapper missing"
    assert "x-cloak" not in wrapper.group(0)

    # x-cloak survives only on the pre-reveal full-key spans.
    cloaked = re.findall(r"<[^>]*x-cloak[^>]*>", src)
    assert cloaked, "expected the full-key reveal spans to stay x-cloaked"
    for tag in cloaked:
        assert "keys-card__full" in tag, tag

    # The 120ms artificial delay is gone; hydration swaps immediately.
    assert "setTimeout" not in src
    assert 'x-init="hydrated = true"' in src
    # Coding convention: no inline style attributes anywhere on the page.
    assert 'style="' not in src


# ---------------------------------------------------------------------------
# Distinct key states + CTAs (VAL-ACC-003, VAL-ACC-002)
# ---------------------------------------------------------------------------

def test_active_expired_and_revoked_are_distinct(client, db, buyer):
    user, product = buyer
    day, month = product.tiers.all()
    now = datetime.utcnow()
    _make_key(db, user, product, day, "BEAZT-ACTIVE-0001",
              expires_at=now + timedelta(days=16))
    _make_key(db, user, product, day, "BEAZT-EXPIRE-0002",
              expires_at=now - timedelta(days=2))
    _make_key(db, user, product, month, "BEAZT-REVOKED-003",
              expires_at=now + timedelta(days=10), is_active=False,
              chairfbi_key_id="CF-8842")
    html = client.get("/my-keys").data.decode()

    for state in ("active", "expired", "revoked"):
        assert html.count(f'data-key-state="{state}"') == 1, state

    active = _card(html, "active")
    expired = _card(html, "expired")
    revoked = _card(html, "revoked")

    # Distinct labels: Active / Expired / Revoked.
    assert ">Active<" in active
    assert ">Expired<" in expired
    assert ">Revoked<" in revoked

    # Expired: renewal CTA targets the product page, no loader download.
    assert 'href="/product/rust-esp-lite"' in expired
    assert "Renew" in expired
    assert "Download Loader" not in expired

    # Revoked: distinct copy + support path, never a renewal CTA.
    assert "revoked" in revoked.lower()
    assert "Renew" not in revoked
    assert "Download Loader" not in revoked
    assert re.search(r'Contact support|Get help', revoked, re.I)

    # Loader download exists for the active key only.
    assert "Download Loader" in active
    assert html.count("Download Loader") == 1

    # Distinct state copy: expired says the licence ended, revoked says why.
    assert "ended" in expired.lower()
    assert "support" in revoked.lower()


def test_expiry_remaining_math_is_accurate(client, db, buyer):
    user, product = buyer
    tier = product.tiers.all()[0]
    _make_key(db, user, product, tier, "BEAZT-DAYS-0001",
              expires_at=datetime.utcnow() + timedelta(days=16, minutes=5))
    _make_key(db, user, product, tier, "BEAZT-HOURS-0002",
              expires_at=datetime.utcnow() + timedelta(hours=3))
    html = client.get("/my-keys").data.decode()

    assert "16 days remaining" in html
    assert "Expires today" in html


def test_chairfbi_meta_labelled_license_id_not_ref(client, db, buyer):
    user, product = buyer
    tier = product.tiers.all()[0]
    _make_key(db, user, product, tier, "BEAZT-LABEL-0001",
              expires_at=datetime.utcnow() + timedelta(days=5),
              chairfbi_key_id="CF-9911")
    html = client.get("/my-keys").data.decode()

    assert "License ID" in html
    assert "CF-9911" in html
    assert ">Ref<" not in html


# ---------------------------------------------------------------------------
# Order history (VAL-ACC-004)
# ---------------------------------------------------------------------------

def test_order_history_lists_completed_orders_only(client, db, buyer, make_product):
    user, product = buyer
    day, month = product.tiers.all()
    apex = make_product("apex-esp", name="Apex ESP", tiers=[("1 Week", 7, 2200, False)])
    apex_tier = apex.tiers.all()[0]

    _make_order(db, user, month, session_id="sess-hist-1", qty=1, days_ago=12)
    _make_order(db, user, day, session_id="sess-hist-2", qty=3, days_ago=6)
    _make_order(db, user, apex_tier, session_id="sess-pending-1",
                status="pending", days_ago=1)
    _make_order(db, user, apex_tier, session_id="sess-await-1",
                status="awaiting_keys", days_ago=2)

    html = client.get("/my-keys").data.decode()

    # Exactly the completed orders render as history rows.
    assert html.count("data-order-row") == 2
    row = re.search(r"<tr[^>]*data-order-row.*?</tr>", html, re.S).group(0)
    assert "Rust ESP Lite" in row
    assert "1 Month" in row or "1 Day" in row

    # Date, plan, quantity and status are all present in the history.
    history = html[html.index("keys-orders"):]
    assert "Completed" in history
    assert re.search(r"\d{2} \w{3} \d{4}", history)
    assert ">3<" in history  # qty of the second completed order

    # The pending/apex order never lands in the history section; it only
    # feeds the pending explainer.
    assert html.count("Apex ESP") == 1
    assert "Apex ESP" not in history


def test_order_history_shows_light_note_for_accounts_without_orders(client, db, buyer):
    user, product = buyer
    html = client.get("/my-keys").data.decode()

    assert "keys-orders" in html
    assert "No completed orders yet" in html
    assert "data-order-row" not in html


# ---------------------------------------------------------------------------
# Pending explainer + honest copy
# ---------------------------------------------------------------------------

def test_pending_explainer_kept_with_canonical_delivery_promise(client, db, buyer):
    user, product = buyer
    tier = product.tiers.all()[0]
    _make_order(db, user, tier, session_id="sess-await-2",
                status="awaiting_keys", days_ago=0)
    html = client.get("/my-keys").data.decode()

    assert "Processing order" in html
    # One canonical delivery promise (design-direction copy canon).
    assert "usually within seconds" in html
    assert "usually within minutes" not in html


# ---------------------------------------------------------------------------
# Filter chips (VAL-ACC-006) + empty state (VAL-CROSS-003)
# ---------------------------------------------------------------------------

def test_filter_chips_render_with_counts(client, db, buyer):
    user, product = buyer
    tier = product.tiers.all()[0]
    now = datetime.utcnow()
    _make_key(db, user, product, tier, "BEAZT-FILT-0001", expires_at=now + timedelta(days=9))
    _make_key(db, user, product, tier, "BEAZT-FILT-0002", expires_at=now - timedelta(days=1))
    _make_key(db, user, product, tier, "BEAZT-FILT-0003", is_active=False)
    html = client.get("/my-keys").data.decode()

    for chip in ("all", "active", "expired"):
        assert f'data-filter="{chip}"' in html, chip
    assert "All (3)" in html
    assert "Active (1)" in html
    assert "Expired (2)" in html  # expired + revoked are the non-usable set


def test_fresh_account_sees_empty_state_with_catalogue_cta(client, db, buyer):
    html = client.get("/my-keys").data.decode()

    assert "No keys yet" in html
    assert 'href="/cheats"' in html
    assert "Browse plans" in html
    assert "data-key-state" not in html
