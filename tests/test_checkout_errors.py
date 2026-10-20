"""Checkout create-session error hardening (VAL-FUN-003 / VAL-FUN-004).

Internal exception strings must never reach the buyer UI: every error
response from /checkout/create-session carries a human message with a
path to support, while the full exception detail is logged server-side
only. An unconfigured IVNO gateway degrades to a 503
``{error, gateway_unavailable: true}`` payload that the product page JS
maps to a disabled card option with an explanation; PayFast stays
usable and its signing/gateway logic is untouched.
"""

import pathlib

from models import Order, PricingTier

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRODUCT_TEMPLATE = REPO_ROOT / "templates" / "product.html"

# Distinctive markers that must NEVER appear in a buyer-facing response.
IVNO_CANARY = "IVNO-CANARY-internal-detail-9f3a"
FX_CANARY = "PAYFAST-FX-CANARY-internal-8b71"

# 1 Day £9 (PayFast path) + 30 Days £25 (clears the £20 card minimum).
TIERS = [("1 Day", 1, 900, False), ("30 Days", 30, 2500, False)]


def _expensive_tier(product):
    return (
        PricingTier.query.filter_by(product_id=product.id)
        .order_by(PricingTier.duration_days.desc())
        .first()
    )


def _unconfigured(monkeypatch):
    monkeypatch.setattr(
        "routes.checkout.get_ivno_config",
        lambda: {"api_key": "", "api_secret": "", "webhook_secret": ""},
    )


def _configured(monkeypatch):
    monkeypatch.setattr(
        "routes.checkout.get_ivno_config",
        lambda: {"api_key": "test-key", "api_secret": "test-secret", "webhook_secret": ""},
    )


class _BoomIvno:
    """Stub gateway client whose create_payment raises an internal error."""

    def __init__(self, *args, **kwargs):
        pass

    def create_payment(self, **kwargs):
        raise RuntimeError(IVNO_CANARY)


class _RejectIvno:
    """Stub gateway client returning a non-success payload with internals."""

    def __init__(self, *args, **kwargs):
        pass

    def create_payment(self, **kwargs):
        return {"success": False, "message": IVNO_CANARY}


def _fx_boom():
    raise RuntimeError(FX_CANARY)


# --- IVNO unconfigured: 503 + gateway_unavailable shape (VAL-FUN-004) ------

class TestIvnoUnconfigured:
    def test_returns_503_with_gateway_unavailable_flag(self, buyer_client, make_product, monkeypatch, post_form):
        _unconfigured(monkeypatch)
        product = make_product("card-unconfigured", tiers=TIERS)
        resp = post_form(buyer_client, "/checkout/create-session",
                         {"tier_id": _expensive_tier(product).id, "quantity": "1",
                          "gateway": "ivno"})
        assert resp.status_code == 503
        data = resp.get_json()
        assert data.get("gateway_unavailable") is True
        error = data.get("error", "")
        assert error, "503 payload must still carry a human error message"
        assert error != "Ivno not configured"
        assert "ivno" not in error.lower(), f"internal gateway name leaked: {error!r}"

    def test_error_is_human_with_payfast_and_support_pointer(self, buyer_client, make_product, monkeypatch, post_form):
        _unconfigured(monkeypatch)
        product = make_product("card-unconfigured-copy", tiers=TIERS)
        resp = post_form(buyer_client, "/checkout/create-session",
                         {"tier_id": _expensive_tier(product).id, "quantity": "1",
                          "gateway": "ivno"})
        error = resp.get_json()["error"]
        assert "payfast" in error.lower()
        assert "support" in error.lower()

    def test_no_pending_order_created(self, buyer_client, make_product, monkeypatch, post_form):
        _unconfigured(monkeypatch)
        product = make_product("card-unconfigured-order", tiers=TIERS)
        post_form(buyer_client, "/checkout/create-session",
                  {"tier_id": _expensive_tier(product).id, "quantity": "1",
                   "gateway": "ivno"})
        assert Order.query.count() == 0


# --- No internal exception string reaches the buyer (VAL-FUN-003) ----------

class TestNoInternalStringLeaks:
    def test_ivno_exception_not_echoed(self, buyer_client, make_product, monkeypatch, post_form):
        _configured(monkeypatch)
        monkeypatch.setattr("utils.ivno.IvnoPayments", _BoomIvno)
        product = make_product("card-exception", tiers=TIERS)
        resp = post_form(buyer_client, "/checkout/create-session",
                         {"tier_id": _expensive_tier(product).id, "quantity": "1",
                          "gateway": "ivno"})
        assert resp.status_code == 500
        body = resp.get_data(as_text=True)
        assert IVNO_CANARY not in body
        error = resp.get_json()["error"]
        assert error and IVNO_CANARY not in error
        assert "support" in error.lower()

    def test_ivno_gateway_rejection_message_not_echoed(self, buyer_client, make_product, monkeypatch, post_form):
        _configured(monkeypatch)
        monkeypatch.setattr("utils.ivno.IvnoPayments", _RejectIvno)
        product = make_product("card-rejected", tiers=TIERS)
        resp = post_form(buyer_client, "/checkout/create-session",
                         {"tier_id": _expensive_tier(product).id, "quantity": "1",
                          "gateway": "ivno"})
        assert resp.status_code == 500
        body = resp.get_data(as_text=True)
        assert IVNO_CANARY not in body
        error = resp.get_json()["error"]
        assert error and "support" in error.lower()

    def test_payfast_exception_not_echoed(self, buyer_client, make_product, monkeypatch, post_form):
        monkeypatch.setattr("routes.checkout._get_gbp_to_zar", _fx_boom)
        product = make_product("pf-exception", tiers=TIERS)
        resp = post_form(buyer_client, "/checkout/create-session",
                         {"tier_id": _expensive_tier(product).id, "quantity": "1",
                          "gateway": "payfast"})
        assert resp.status_code == 500
        body = resp.get_data(as_text=True)
        assert FX_CANARY not in body
        error = resp.get_json()["error"]
        assert error and FX_CANARY not in error
        assert "support" in error.lower()


# --- Product page gateway availability flag (server-rendered) --------------

class TestProductPageGatewayFlag:
    def test_flag_false_when_ivno_unconfigured(self, client, make_product, monkeypatch):
        monkeypatch.setattr(
            "routes.main.get_ivno_config",
            lambda: {"api_key": "", "api_secret": "", "webhook_secret": ""},
        )
        make_product("flag-unconfigured", tiers=TIERS)
        html = client.get("/product/flag-unconfigured").get_data(as_text=True)
        assert "window.BEAZT_CHECKOUT" in html
        assert "cardEnabled: false" in html

    def test_flag_true_when_ivno_configured(self, client, make_product, monkeypatch):
        monkeypatch.setattr(
            "routes.main.get_ivno_config",
            lambda: {"api_key": "test-key", "api_secret": "test-secret", "webhook_secret": ""},
        )
        make_product("flag-configured", tiers=TIERS)
        html = client.get("/product/flag-configured").get_data(as_text=True)
        assert "cardEnabled: true" in html


# --- Template wiring: gateway_unavailable maps to a disabled card option ----

class TestTemplateWiring:
    def test_checkout_js_maps_gateway_unavailable(self):
        src = PRODUCT_TEMPLATE.read_text(encoding="utf-8")
        assert "data.gateway_unavailable" in src, \
            "handleCheckout must react to the 503 gateway_unavailable payload"
        assert "cardUnavailable" in src, "component state must track card availability"

    def test_card_radio_disableable_but_payfast_never_disabled(self):
        src = PRODUCT_TEMPLATE.read_text(encoding="utf-8")
        card_input = '<input type="radio" name="gateway" value="ivno" x-model="selectedGateway" aria-label="Pay with card" :disabled="cardUnavailable">'
        assert card_input in src, "card radio must be disableable via cardUnavailable"
        payfast_input = '<input type="radio" name="gateway" value="payfast" x-model="selectedGateway" aria-label="Pay with PayFast">'
        assert payfast_input in src, "PayFast radio must stay selectable"

    def test_unavailable_state_carries_explanation_and_support_link(self):
        src = PRODUCT_TEMPLATE.read_text(encoding="utf-8")
        assert "pd-gateway-note" in src, "disabled card state must show an explanation"
        assert "contact support" in src.lower()

    def test_checkout_errors_raise_a_dismissible_toast(self):
        src = PRODUCT_TEMPLATE.read_text(encoding="utf-8")
        assert "window.BEAZT.toast" in src, \
            "checkout errors must surface through the persistent toast system"
