"""NFAHub integration: catalog parsing, fulfillment, admin retry, seeding."""

import pytest

from models import db, Order, Product, PricingTier, Key
from utils.nfahub import extract_credentials, iter_variants
import utils.nfahub as nfahub_mod
import config as config_mod


# --- Credential extraction --------------------------------------------------

def test_extract_credentials_bare_string():
    assert extract_credentials("user@mail.com:pw") == ["user@mail.com:pw"]

def test_extract_credentials_credentials_field():
    payload = {"orderId": 5, "credentials": "user1:pw1\nuser2:pw2"}
    assert extract_credentials(payload) == ["user1:pw1", "user2:pw2"]

def test_extract_credentials_identity_password_pair():
    payload = {"items": [{"email": "a@b.c", "password": "secret"}]}
    assert extract_credentials(payload) == ["a@b.c:secret"]

def test_extract_credentials_nested_list_and_dedupe():
    payload = [{"key": "K1"}, {"key": "K1"}, {"key": "K2"}]
    assert extract_credentials(payload) == ["K1", "K2"]

def test_extract_credentials_empty_payload():
    assert extract_credentials({"status": "ok"}) == []
    assert extract_credentials(None) == []


# --- Catalog flattening -------------------------------------------------------

def test_iter_variants_nested_products():
    catalog = {"products": [
        {"name": "CS2", "variants": [
            {"variantId": "v1", "priceCents": 64, "stock": 177},
            {"variantId": "v2", "priceCents": 72, "stock": 0},
        ]},
    ]}
    rows = iter_variants(catalog)
    assert [r["variant_id"] for r in rows] == ["v1", "v2"]
    assert rows[0]["name"] == "CS2"
    assert rows[0]["price_cents"] == 64

def test_iter_variants_flat_list_snake_case():
    rows = iter_variants([{"variant_id": 9, "name": "DayZ NFA Account",
                           "price_cents": 55, "stock_count": 1}])
    assert rows == [{"variant_id": "9", "name": "DayZ NFA Account",
                     "price_cents": 55, "stock": 1}]


# --- Fulfillment ---------------------------------------------------------------

class _FakeNFAHub:
    orders_bought = []

    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key

    def buy(self, variant_id, quantity=1):
        _FakeNFAHub.orders_bought.append((variant_id, quantity))
        return {"orderId": "NFA-777", "items": [
            {"credentials": f"user{i}@mail.com:pw{i}"} for i in range(quantity)
        ]}


@pytest.fixture
def nfahub_enabled(monkeypatch):
    monkeypatch.setattr(config_mod.Config, "NFAHUB_API_KEY", "test-nfahub-key", raising=False)
    monkeypatch.setattr(nfahub_mod, "NFAHub", _FakeNFAHub)
    _FakeNFAHub.orders_bought = []
    return _FakeNFAHub


def _make_nfahub_order(db, make_user, make_product, slug="nfahub-rust", quantity=1):
    buyer = make_user("nfa-buyer")
    product = make_product(slug, name="Rust NFA Accounts", key_source="nfahub",
                           status="account", game="Rust")
    tier = product.tiers.first()
    tier.nfahub_variant_id = "42"
    tier.duration_days = 0
    db.session.commit()
    order = Order(user_id=buyer.id, tier_id=tier.id, status="paid", quantity=quantity)
    db.session.add(order)
    db.session.commit()
    return order, product, tier


def test_nfahub_fulfillment_creates_keys(db, make_user, make_product, nfahub_enabled):
    from routes.checkout import handle_fulfillment
    order, product, tier = _make_nfahub_order(db, make_user, make_product)
    handle_fulfillment(order)

    assert order.status == "completed"
    keys = Key.query.filter_by(order_id=order.id).all()
    assert len(keys) == 1
    assert keys[0].key_value == "user0@mail.com:pw0"
    assert keys[0].nfahub_order_id == "NFA-777"
    assert keys[0].expires_at is None  # accounts do not expire
    assert keys[0].is_active is True
    assert nfahub_enabled.orders_bought == [("42", 1)]

def test_nfahub_multi_account_buys_bundle(db, make_user, make_product, nfahub_enabled):
    from routes.checkout import handle_fulfillment
    order, _, _ = _make_nfahub_order(db, make_user, make_product, quantity=3)
    handle_fulfillment(order)

    assert nfahub_enabled.orders_bought == [("42", 3)]
    keys = Key.query.filter_by(order_id=order.id).all()
    assert len(keys) == 3

def test_nfahub_buy_failure_awaits_keys(db, make_user, make_product, nfahub_enabled, monkeypatch):
    from routes.checkout import handle_fulfillment
    order, _, _ = _make_nfahub_order(db, make_user, make_product)

    class _Boom(_FakeNFAHub):
        def buy(self, variant_id, quantity=1):
            raise nfahub_mod.NFAHubError("NFAHub buy: balance/stock/order conflict", status=409)

    monkeypatch.setattr(nfahub_mod, "NFAHub", _Boom)
    handle_fulfillment(order)

    assert order.status == "awaiting_keys"
    assert Key.query.filter_by(order_id=order.id).count() == 0

def test_nfahub_without_api_key_awaits_keys(db, make_user, make_product, monkeypatch):
    from routes.checkout import handle_fulfillment
    monkeypatch.setattr(config_mod.Config, "NFAHUB_API_KEY", "", raising=False)
    order, _, _ = _make_nfahub_order(db, make_user, make_product)
    handle_fulfillment(order)

    assert order.status == "awaiting_keys"
    assert Key.query.filter_by(order_id=order.id).count() == 0

def test_non_nfahub_tier_skips_nfahub_path(db, make_user, make_product):
    """No variant bound -> try_nfahub opts out, fulfillment lands on awaiting."""
    from routes.checkout import handle_fulfillment, try_nfahub
    buyer = make_user("plain-buyer")
    product = make_product("plain-product", key_source="pool")
    tier = product.tiers.first()
    order = Order(user_id=buyer.id, tier_id=tier.id, status="paid")
    db.session.add(order)
    db.session.commit()

    assert try_nfahub(order, product, tier) == ([], "", None)
    handle_fulfillment(order)
    assert order.status == "awaiting_keys"  # pool is empty for this tier


# --- Admin retry action ----------------------------------------------------------

def test_admin_fulfill_nfahub_order(admin_client, post_form, db, make_user, make_product,
                                    nfahub_enabled):
    order, product, tier = _make_nfahub_order(db, make_user, make_product,
                                              slug="nfahub-cs2", quantity=2)
    order.status = "awaiting_keys"
    db.session.commit()

    resp = post_form(admin_client, f"/admin/orders/{order.id}/fulfill")
    assert resp.status_code == 302
    assert order.status == "completed"
    keys = Key.query.filter_by(order_id=order.id).all()
    assert len(keys) == 2
    assert all(k.nfahub_order_id == "NFA-777" for k in keys)


# --- Storefront status taxonomy ----------------------------------------------------

def test_account_status_is_neutral_not_risky():
    from utils.catalogue import STATUS_LABELS, normalize_status
    assert STATUS_LABELS["account"] == "Account"
    assert normalize_status("account") == "account"

def test_account_product_card_uses_account_label(db, make_product):
    from utils.catalogue import build_cards
    product = make_product("card-nfa", key_source="nfahub", status="account")
    card = build_cards([product])[0]
    assert card["status"] == "account"
    assert card["status_label"] == "Account"


# --- My Keys activation surface ----------------------------------------------------

def test_my_keys_shows_activate_on_nfahub(buyer_client, db, make_product):
    """NFA account key cards show the redemption button, not a loader link."""
    from datetime import datetime
    from models import Key, Setting, User
    Setting.set("nfahub_redemption_url", "https://nfahub.example/redeem")
    product = make_product("nfahub-keys", key_source="nfahub", status="account")
    tier = product.tiers.first()
    buyer = User.query.filter_by(username="buyer").first()
    db.session.add(Key(user_id=buyer.id, product_id=product.id, tier_id=tier.id,
                       key_value="user@mail.com:pw", expires_at=None, is_active=True,
                       assigned_at=datetime.utcnow()))
    db.session.commit()

    resp = buyer_client.get("/my-keys")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Activate on NFAHub" in body
    assert "https://nfahub.example/redeem" in body
    assert "Account credentials" in body
    assert "Download Loader" not in body

def test_my_keys_non_nfa_keeps_loader_button(buyer_client, db, make_product):
    from datetime import datetime, timedelta
    from models import Key, Setting, User
    Setting.set("nfahub_redemption_url", "https://nfahub.example/redeem")
    product = make_product("plain-keys", key_source="pool")
    tier = product.tiers.first()
    buyer = User.query.filter_by(username="buyer").first()
    db.session.add(Key(user_id=buyer.id, product_id=product.id, tier_id=tier.id,
                       key_value="POOL-KEY-1234-5678", expires_at=datetime.utcnow() + timedelta(days=7),
                       is_active=True, assigned_at=datetime.utcnow()))
    db.session.commit()

    resp = buyer_client.get("/my-keys")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Download Loader" in body
    assert "Activate on NFAHub" not in body


# --- NFA storefront page + nav -----------------------------------------------------

def test_nfa_page_lists_only_nfa_products(client, db, make_product):
    make_product("nfahub-page-rust", name="Rust NFA Accounts", key_source="nfahub",
                 status="account", game="Rust")
    make_product("plain-page-cheat", name="Plain Cheat", key_source="pool")
    resp = client.get("/nfa")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Rust NFA Accounts" in body
    assert "Plain Cheat" not in body

def test_nfa_nav_link_present(client, db, make_product):
    make_product("nfahub-nav", key_source="nfahub", status="account")
    for path in ("/", "/cheats"):
        body = client.get(path).data.decode("utf-8")
        assert "NFA Accounts" in body, f"nav link missing on {path}"


# --- Seed script -------------------------------------------------------------------

def test_seed_nfahub_products(db, monkeypatch, capsys):
    import scripts.seed_nfahub_products as seed

    monkeypatch.setattr(seed, "_eur_to_gbp_rate", lambda: 0.86)
    monkeypatch.delenv("NFAHUB_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["seed_nfahub_products.py", "--markup", "1.0"])

    assert seed.main() == 0
    assert seed.main() == 0  # idempotent

    assert Product.query.filter(Product.slug.startswith("nfahub-")).count() == 5
    tiers = (PricingTier.query.join(Product).filter(Product.slug == "nfahub-rust")
             .order_by(PricingTier.label).all())
    assert len(tiers) == 10
    for tier in tiers:
        assert tier.duration_days == 0
        assert tier.is_subscription is False
        assert tier.nfahub_variant_id is None  # no API key -> unbound
    # €0.81 -> 0.81 * 0.86 = 69.66p -> ceil to nearest 5p = 70p
    by_label = {t.label: t.price_pence for t in tiers}
    assert by_label["0-100 hours"] == 70
    # €2.13 -> 183.18p -> 185p
    assert by_label["1000-1500 hours"] == 185
    out = capsys.readouterr().out
    assert "cost price" in out or "markup: 1.0x" in out
