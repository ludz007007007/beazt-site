import logging
import hashlib
import hmac
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, url_for
from flask_login import current_user, login_required
from models import db, PricingTier, Order, Key, Product, Setting
from config import get_ivno_config, get_license_api_config
from utils.license_api import LicenseAPI

checkout_bp = Blueprint("checkout", __name__)
logger = logging.getLogger(__name__)

# Buyer-facing checkout error messages (VAL-FUN-003/004 hardening).
# Internal exception details are logged server-side only — responses never
# echo str(e), tracebacks, or gateway internals back to the buyer; they carry
# a human message plus a path to support instead.
CARD_GATEWAY_UNAVAILABLE_MSG = (
    "Card payments are temporarily unavailable — please use PayFast or contact support."
)
CARD_PAYMENT_FAILED_MSG = (
    "We couldn't start your card payment. Please try PayFast or contact support."
)
PAYFAST_PAYMENT_FAILED_MSG = (
    "We couldn't start your checkout. Please try again or contact support."
)

_ZAR_RATE = None
_ZAR_RATE_TIME = None


def _get_gbp_to_zar():
    import requests as _r
    global _ZAR_RATE, _ZAR_RATE_TIME
    if _ZAR_RATE and _ZAR_RATE_TIME and (datetime.utcnow() - _ZAR_RATE_TIME).seconds < 600:
        return _ZAR_RATE
    try:
        resp = _r.get("https://open.er-api.com/v6/latest/GBP", timeout=5)
        data = resp.json()
        _ZAR_RATE = data["rates"]["ZAR"]
        _ZAR_RATE_TIME = datetime.utcnow()
        return _ZAR_RATE
    except Exception:
        return 24.0  # fallback GBP→ZAR


def _payfast_vars(order, amount, tier):
    pf_host = "https://www.payfast.co.za/eng/process"
    merchant_id = Setting.get("payfast_merchant_id") or ""
    merchant_key = Setting.get("payfast_merchant_key") or ""
    passphrase = Setting.get("payfast_passphrase") or ""
    name = Setting.get("payfast_item_name") or "Private Development"

    pf_data = {
        "merchant_id": merchant_id,
        "merchant_key": merchant_key,
        "return_url": url_for("main.my_keys", _external=True),
        "cancel_url": url_for("main.product_detail", slug=tier.product.slug, _external=True),
        "notify_url": url_for("checkout.payfast_notify", _external=True),
        "name_first": current_user.username or "",
        "email_address": current_user.email,
        "m_payment_id": str(order.id),
        "amount": f"{amount:.2f}",
        "item_name": name,
    }

    from urllib.parse import quote_plus
    WHITELIST = [
        "merchant_id", "merchant_key", "return_url", "cancel_url",
        "notify_url", "name_first", "name_last", "email_address",
        "cell_number", "m_payment_id", "amount", "item_name",
        "item_description", "custom_int1", "custom_int2", "custom_int3",
        "custom_int4", "custom_int5", "custom_str1", "custom_str2",
        "custom_str3", "custom_str4", "custom_str5",
        "email_confirmation", "confirmation_address", "currency",
        "payment_method", "subscription_type", "billing_date",
        "recurring_amount", "frequency", "cycles",
    ]

    param_string = ""
    for field in WHITELIST:
        if field in pf_data and pf_data[field]:
            val = str(pf_data[field]).strip()
            param_string += f"&{field}={quote_plus(val)}"
    param_string = param_string.lstrip("&")
    if passphrase:
        param_string += "&passphrase=" + quote_plus(passphrase.strip())

    pf_data["signature"] = hashlib.md5(param_string.encode()).hexdigest()
    return pf_host, pf_data


@checkout_bp.route("/create-session", methods=["POST"])
@login_required
def create_session():
    tier_id = request.form.get("tier_id")
    raw_quantity = (request.form.get("quantity") or "1").strip()
    gateway = request.form.get("gateway", "payfast")

    if not tier_id:
        return jsonify({"error": "No tier selected"}), 400
    try:
        tier_id_int = int(tier_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid tier selected."}), 400
    try:
        quantity = int(float(raw_quantity))
    except (TypeError, ValueError, OverflowError):
        return jsonify({"error": "Quantity must be a whole number between 1 and 10."}), 400
    if quantity < 1 or quantity > 10:
        return jsonify({"error": "Quantity must be between 1 and 10."}), 400

    tier = db.session.get(PricingTier, tier_id_int)
    if not tier:
        return jsonify({"error": "Invalid tier"}), 400

    order_total = tier.price_pounds * quantity

    if gateway == "ivno":
        if order_total < 20:
            return jsonify({"error": f"Minimum £20 required for card payments. Your total: £{order_total:.2f}"}), 400
        return _create_ivno_payment(tier, quantity, order_total)

    return _create_payfast_payment(tier, quantity, order_total)


def _create_ivno_payment(tier, quantity, order_total):
    cfg = get_ivno_config()
    if not cfg["api_key"]:
        # Gateway not set up (no credentials in Settings or env): degrade
        # loudly for the UI but quietly for the buyer — 503 +
        # gateway_unavailable lets the product page disable the card option
        # instead of leaking "Ivno not configured".
        logger.warning(
            "IVNO card gateway unconfigured (api_key missing); "
            "create-session rejected with 503 gateway_unavailable"
        )
        return jsonify({
            "error": CARD_GATEWAY_UNAVAILABLE_MSG,
            "gateway_unavailable": True,
        }), 503

    order = Order(user_id=current_user.id, tier_id=tier.id, status="pending", quantity=quantity)
    db.session.add(order)
    db.session.flush()
    db.session.commit()

    try:
        from utils.ivno import IvnoPayments
        ivno = IvnoPayments(api_key=cfg["api_key"], api_secret=cfg["api_secret"])
        domain = request.host.split(":")[0] if ":" in (request.host or "") else request.host

        result = ivno.create_payment(
            amount=order_total,
            currency="GBP",
            order_id=f"BEAZT-{order.id}",
            return_url=url_for("main.my_keys", _external=True),
            email=current_user.email,
            webhook_url=url_for("checkout.ivno_webhook", _external=True),
            domain=domain,
            fee_preference="absorb",
        )

        if not result.get("success") or not result.get("payment_url"):
            # Gateway-reported failure: log the raw reason server-side, show
            # the buyer a human message (never the gateway's internals).
            logger.error("Ivno payment rejected by gateway: %s",
                         result.get("message", "no message returned"))
            return jsonify({"error": CARD_PAYMENT_FAILED_MSG}), 500

        return jsonify({"payment_url": result["payment_url"]})
    except Exception:
        logger.exception("Ivno payment failed")
        return jsonify({"error": CARD_PAYMENT_FAILED_MSG}), 500


def _create_payfast_payment(tier, quantity, order_total):
    order = Order(user_id=current_user.id, tier_id=tier.id, status="pending", quantity=quantity)
    db.session.add(order)
    db.session.flush()
    db.session.commit()

    try:
        zar_amount = round(order_total * _get_gbp_to_zar(), 2)
        pf_host, pf_data = _payfast_vars(order, zar_amount, tier)
        return jsonify({
            "payment_url": pf_host,
            "payfast_data": pf_data,
            "payfast": True,
        })
    except Exception:
        logger.exception("PayFast payment failed")
        return jsonify({"error": PAYFAST_PAYMENT_FAILED_MSG}), 500


def _expected_payfast_amount(order):
    """Recompute the ZAR amount PayFast should report for this order.

    Mirrors ``_create_payfast_payment``: GBP order total (tier price x
    quantity) converted at the current GBP->ZAR rate, rounded to 2dp.
    Returns ``None`` when the order has no tier (cannot reconcile).
    """
    tier = order.tier
    if not tier:
        return None
    quantity = getattr(order, "quantity", 1) or 1
    order_total = tier.price_pounds * quantity
    return round(order_total * _get_gbp_to_zar(), 2)


def _amounts_reconcile(reported, expected):
    """Compare ITN amount_gross to the expected amount at 2-decimal precision."""
    try:
        return round(float(reported), 2) == round(float(expected), 2)
    except (TypeError, ValueError):
        return False


@checkout_bp.route("/payfast-notify", methods=["POST"])
def payfast_notify():
    logger.info("PayFast ITN received: %s", dict(request.form))
    pf_host, pf_data, pf_param_string = "https://www.payfast.co.za/eng/query/validate", {}, ""
    for k, v in request.form.items():
        if k != "signature":
            pf_data[k] = v
            pf_param_string += f"&{k}={v}"
    pf_param_string = pf_param_string[1:]

    import requests as _r
    resp = _r.post(pf_host, data=pf_data, params=pf_param_string, timeout=15)
    logger.info("PayFast validation response: %s", resp.text)
    if resp.text != "VALID":
        return "INVALID", 400

    order_id = int(pf_data.get("m_payment_id", 0))
    payment_status = str(pf_data.get("payment_status", "") or "")
    logger.info("PayFast ITN for order %s, payment_status=%s", order_id, payment_status or "?")
    order = db.session.get(Order, order_id)
    if not order:
        logger.warning("PayFast ITN: order %s not found", order_id)
        return "OK"

    # BLK-2: fulfill ONLY on COMPLETE (case-insensitive) with reconciled amount.
    # Non-COMPLETE or mismatched ITNs are acknowledged (200) without fulfillment
    # so PayFast does not retry, but no keys are delivered.
    if payment_status.upper() != "COMPLETE":
        logger.warning("PayFast ITN: order %s not COMPLETE (payment_status=%r) — no fulfillment",
                       order_id, payment_status)
        return "OK"

    expected = _expected_payfast_amount(order)
    if expected is None:
        logger.warning("PayFast ITN: order %s has no tier — cannot reconcile amount, no fulfillment", order_id)
        return "OK"
    if not _amounts_reconcile(pf_data.get("amount_gross"), expected):
        logger.warning("PayFast ITN: order %s amount mismatch (reported=%r expected=%.2f) — no fulfillment",
                       order_id, pf_data.get("amount_gross"), expected)
        return "OK"

    if order.status != "completed":
        logger.info("Fulfilling order %s", order.id)
        handle_fulfillment(order)
    else:
        logger.info("Order %s already completed", order.id)
    return "OK"


def _get_ivno_webhook_secret():
    """Webhook shared secret: Settings ivno_api_secret with env fallback."""
    cfg = get_ivno_config()
    return (cfg.get("webhook_secret") or "").strip()


def _ivno_webhook_authenticated(secret):
    """Accept a shared-secret header OR an HMAC-SHA256 signature of the raw body."""
    provided = (request.headers.get("X-Webhook-Secret") or "").strip()
    if provided:
        # Compare bytes: str compare_digest rejects non-ASCII with TypeError.
        return hmac.compare_digest(provided.encode("utf-8"), secret.encode("utf-8"))
    signature = (request.headers.get("X-Webhook-Signature") or "").strip()
    if signature:
        digest = hmac.new(secret.encode(), request.get_data(cache=True), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.lower().encode("utf-8"), digest.encode("ascii"))
    return False


@checkout_bp.route("/ivno-webhook", methods=["POST"])
def ivno_webhook():
    secret = _get_ivno_webhook_secret()
    if not secret:
        logger.warning("IVNO webhook rejected: no webhook secret configured")
        return jsonify({"error": "Webhook authentication not configured"}), 403
    if not _ivno_webhook_authenticated(secret):
        logger.warning("IVNO webhook rejected: invalid or missing authentication "
                       "(path=%s, remote=%s)", request.path, request.remote_addr)
        return jsonify({"error": "Invalid webhook authentication"}), 403

    data = request.get_json(silent=True) or {}
    status = data.get("status", "")
    event = data.get("event", "")
    order_id_raw = data.get("order_id", "")

    if not order_id_raw or not order_id_raw.startswith("BEAZT-"):
        logger.warning("IVNO webhook: malformed order_id %r", order_id_raw)
        return jsonify({"received": True})

    try:
        order_id = int(order_id_raw.replace("BEAZT-", ""))
    except (ValueError, TypeError):
        logger.warning("IVNO webhook: unparseable order_id %r", order_id_raw)
        return jsonify({"received": True})

    order = db.session.get(Order, order_id)
    if not order:
        logger.warning("IVNO webhook: order %s not found — no fulfillment", order_id)
        return jsonify({"received": True})

    if status == "completed" and order.status != "completed":
        handle_fulfillment(order)

    return jsonify({"received": True})


def _extract_key_strings(keys_data):
    """Extract key strings from various License API / ChairFBI response formats."""
    result = []
    if not keys_data:
        return result
    items = keys_data if isinstance(keys_data, list) else [keys_data]
    for k in items:
        if isinstance(k, str):
            result.append(k)
        elif isinstance(k, dict):
            kv = (k.get("key") or k.get("license") or k.get("license_key")
                  or k.get("code") or k.get("value") or k.get("token"))
            if kv:
                result.append(str(kv))
    return result


def _notify_buyer(order, product, tier, keys):
    """Email the buyer their assigned key(s). Best-effort; never raises."""
    try:
        from utils.mailer import notify_key_assigned
        from models import User
        from config import Config
        user = User.query.get(order.user_id) if order.user_id else None
        if not user:
            return
        notify_key_assigned(user, order, product, tier, keys, site_url=Config.SITE_URL)
    except Exception:
        logger.exception("notify_key_assigned failed for order %s", order.id)


def try_license_api(order, product, tier):
    """Attempt to generate keys via the Project Infinity License API.

    Shared by automatic fulfillment (``handle_fulfillment``), the admin
    "Fulfill" button, and the per-order "re-run" action.

    Does NOT mutate the database or commit — the caller is responsible for
    creating ``Key`` rows and setting ``order.status``.

    Returns a tuple ``(key_values, error)``:
      * On success: ``key_values`` is a non-empty list of key strings,
        ``error`` is ``None``.
      * On failure: ``key_values`` is ``[]`` and ``error`` is a human-readable
        description of why (missing config, auth failure, unparseable
        response, exception, etc.).
    """
    if not (product and product.license_api_app_id):
        return [], "No License App ID is configured on this product."

    duration_days = tier.duration_days if tier else 30
    total_keys = (getattr(tier, "bundle_count", 1) or 1) * (getattr(order, "quantity", 1) or 1)

    cfg = get_license_api_config()
    api = LicenseAPI(api_token=cfg["api_token"], base_url=cfg["api_url"], auth_scheme=cfg["auth_scheme"])
    try:
        keys_data = api.create_keys(
            app_id=product.license_api_app_id,
            duration_days=duration_days,
            quantity=total_keys,
        )
        key_values = _extract_key_strings(keys_data)
        if key_values:
            logger.info("License API generated %d key(s) for order %s", len(key_values), order.id)
            return key_values, None
        raw = api.last_response.text[:500] if api.last_response is not None else ""
        logger.warning("License API returned no usable keys for order %s — parsed=%r — raw=%s",
                       order.id, keys_data, raw)
        return [], f"API responded 2xx but no parseable keys. Raw: {raw or str(keys_data)[:300]}"
    except Exception as exc:  # noqa: BLE001 - surfaced to admin for diagnosis
        raw = api.last_response.text[:500] if api.last_response is not None else ""
        status = api.last_response.status_code if api.last_response is not None else "?"
        logger.exception("License API failed for order %s — HTTP %s — raw=%s", order.id, status, raw)
        return [], f"API call failed (HTTP {status}): {exc}"


def handle_fulfillment(order):
    tier = order.tier
    if not tier:
        logger.warning("Fulfill: no tier for order %s", order.id)
        return

    product = tier.product
    product_id = product.id if product else 1
    duration_days = tier.duration_days
    expires_at = datetime.utcnow() + timedelta(days=duration_days)
    total_keys = (getattr(tier, "bundle_count", 1) or 1) * (getattr(order, "quantity", 1) or 1)
    is_sub = bool(getattr(tier, "is_subscription", False))

    logger.info("Fulfilling order %s — product=%s tier=%s key_source=%s app_id=%s private=%s",
                order.id, product.name if product else "?", tier.label,
                product.key_source if product else "?",
                product.license_api_app_id if product else "?",
                product.visibility if product else "?")

    # 1) License API (panel) — primary source, especially for private products
    if product and product.license_api_app_id:
        key_values, err = try_license_api(order, product, tier)
        if key_values:
            order.status = "completed"
            created = []
            for kv in key_values:
                key = Key(user_id=order.user_id, order_id=order.id, product_id=product_id,
                          tier_id=tier.id, key_value=kv, expires_at=expires_at, is_active=True,
                          is_subscription=is_sub)
                db.session.add(key)
                created.append(key)
            db.session.commit()
            logger.info("License API generated %d key(s) for order %s", len(key_values), order.id)
            _notify_buyer(order, product, tier, created)
            return
        logger.warning("License API path failed for order %s — falling back. Reason: %s", order.id, err)

    # 2) Pool key — pre-uploaded unassigned key
    pool_key = (Key.query.filter_by(product_id=product_id, tier_id=tier.id, user_id=None, is_active=False)
                .order_by(Key.created_at.asc()).first())
    if pool_key:
        pool_key.user_id = order.user_id
        pool_key.order_id = order.id
        pool_key.expires_at = expires_at
        pool_key.assigned_at = datetime.utcnow()
        pool_key.is_active = True
        pool_key.is_subscription = is_sub
        order.status = "completed"
        db.session.commit()
        logger.info("Pool key assigned for order %s", order.id)
        _notify_buyer(order, product, tier, [pool_key])
        return

    # 3) ChairFBI — for resold/catalog products with a cheat_id
    if product and product.chairfbi_cheat_id:
        from config import get_chairfbi_config
        cfg = get_chairfbi_config()
        api_token = cfg.get("api_token", "")
        cheat_id = product.chairfbi_cheat_id
        bundle_count = getattr(tier, "bundle_count", 1) or 1
        buy_quantity = getattr(order, "quantity", 1) or 1
        total_keys_cf = bundle_count * buy_quantity
        key_values = []

        if api_token:
            try:
                from utils.chairfbi import ChairFBI
                cf = ChairFBI(api_token=api_token, base_url=cfg.get("api_base"))
                result = cf.create_key(cheat_id=cheat_id, days=duration_days, amount=total_keys_cf)
                key_values = _extract_key_strings(result.get("keys", []))
            except Exception:
                logger.exception("ChairFBI key creation failed for order %s", order.id)

        if key_values:
            order.status = "completed"
            created = []
            for kv in key_values:
                key = Key(user_id=order.user_id, order_id=order.id, product_id=product_id,
                          tier_id=tier.id, key_value=kv, expires_at=expires_at, is_active=True,
                          is_subscription=is_sub,
                          chairfbi_key_id=kv, chairfbi_cheat_id=cheat_id)
                db.session.add(key)
                created.append(key)
            db.session.commit()
            logger.info("ChairFBI generated %d key(s) for order %s", len(key_values), order.id)
            _notify_buyer(order, product, tier, created)
            return

    # 4) No key source available — NEVER generate fake keys
    logger.warning("No key source available for order %s (product=%s, app_id=%s, key_source=%s) — marking awaiting_keys",
                  order.id, product.name if product else "?",
                  product.license_api_app_id if product else "none",
                  product.key_source if product else "none")
    order.status = "awaiting_keys"
    db.session.commit()
