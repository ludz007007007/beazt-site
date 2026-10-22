"""Diagnose and repair stuck NFA account orders (no admin clicks needed).

Run inside the app environment on the server:
    python scripts/nfahub_recover_orders.py [--include-pending] [--buy-missing]

What it does:
  1. Lists recent orders whose tier is NFAHub-backed (nfahub_variant_id set).
  2. Fetches GET /orders + GET /order?id= from NFAHub and prints the raw
     payloads (this also reveals the real API response shapes).
  3. For every local order that is paid/awaiting_keys WITHOUT keys yet:
       - If a matching NFAHub order exists (same variant, not already
         assigned to another local key): deliver ITS credentials — no
         double purchase. Marks the order completed and emails the buyer.
       - Else with --buy-missing: buys the variant now (same as the admin
         Fulfill button) and delivers.
  4. Pending orders are listed as warnings (PayFast never confirmed them);
     pass --include-pending to treat them like awaiting_keys as well.

Safe to re-run: orders with keys, or whose NFAHub order id is already used
by a local key, are skipped.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db, Key, Order, Setting  # noqa: E402

STUCK_STATUSES = ("paid", "awaiting_keys")

VARIANT_KEYS = ("variantId", "variant_id", "variantID", "itemId", "item_id")
ORDER_ID_KEYS = ("id", "orderId", "order_id")


def _pick(payload, keys):
    if not isinstance(payload, dict):
        return None
    for key in keys:
        val = payload.get(key)
        if val is not None:
            return val
    return None


def _iter_order_payloads(orders_payload):
    """Yield plausible per-order dicts from a GET /orders response."""
    if isinstance(orders_payload, list):
        for item in orders_payload:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(orders_payload, dict):
        for key in ("orders", "data", "items", "result"):
            val = orders_payload.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        yield item
                return
        yield orders_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-pending", action="store_true",
                        help="also attempt pending orders (PayFast never confirmed these)")
    parser.add_argument("--buy-missing", action="store_true",
                        help="buy the variant when no existing NFAHub order matches")
    args = parser.parse_args()

    with app.app_context():
        from routes.checkout import _notify_buyer, try_nfahub
        from utils.nfahub import NFAHub, extract_credentials

        api_key = os.getenv("NFAHUB_API_KEY", "") or (Setting.get("nfahub_api_key") or "")
        if not api_key:
            print("No NFAHub API key (env or Settings) — cannot talk to NFAHub.")
            return 1
        api = NFAHub(api_key=api_key)

        print("=== 1. Local orders ===")
        query = (Order.query.join(db.session.query(Order.tier_id).subquery(), Order.tier_id == Order.tier_id)
                 if False else Order.query.order_by(Order.created_at.desc()).limit(20))
        candidates = []
        used_nfahub_ids = {row[0] for row in db.session.query(Key.nfahub_order_id).filter(
            Key.nfahub_order_id.isnot(None)).all() if row[0]}
        for order in query.all():
            tier = order.tier
            product = tier.product if tier else None
            is_nfa = bool(tier is not None and (tier.nfahub_variant_id or "").strip())
            key_count = Key.query.filter_by(order_id=order.id).count()
            if is_nfa:
                status = order.status
                interesting = status in STUCK_STATUSES or (
                    args.include_pending and status == "pending")
                print(f"  order #{order.id}: {product.name if product else '?'} / {tier.label} "
                      f"variant={tier.nfahub_variant_id} status={status} keys={key_count} "
                      f"{'<— STUCK, will attempt' if interesting and key_count == 0 else ''}")
                if interesting and key_count == 0:
                    candidates.append(order)
            elif order.status in ("pending", "paid", "awaiting_keys"):
                print(f"  order #{order.id}: {product.name if product else '?'} "
                      f"status={order.status} (not NFA-backed)")

        if not candidates:
            print("\nNo stuck NFA orders. Nothing to do.")
            return 0

        print("\n=== 2. NFAHub /orders (raw, last payloads) ===")
        try:
            orders_payload = api.orders()
        except Exception as exc:  # noqa: BLE001
            orders_payload = None
            print(f"  GET /orders failed: {exc}")
        import json as _json
        blob = _json.dumps(orders_payload, indent=2)[:4000] if orders_payload else "—"
        print(blob)

        print("\n=== 3. Repair ===")
        # Index NFAHub orders by variant, newest last.
        by_variant = {}
        for item in _iter_order_payloads(orders_payload):
            variant = str(_pick(item, VARIANT_KEYS) or "")
            if variant:
                by_variant.setdefault(variant, []).append(item)

        repaired = 0
        for order in candidates:
            tier = order.tier
            product = tier.product
            variant = (tier.nfahub_variant_id or "").strip()
            credentials, nfahub_order_id = [], ""

            # (a) Recover credentials from an existing NFAHub order — no double buy.
            for item in reversed(by_variant.get(variant, [])):
                oid = str(_pick(item, ORDER_ID_KEYS) or "")
                if oid and oid in used_nfahub_ids:
                    continue  # already delivered against another local order
                creds = extract_credentials(item)
                if creds:
                    credentials, nfahub_order_id = creds, oid
                    # Detailed look-up for cleaner id if the list entry lacks one.
                    if not nfahub_order_id:
                        try:
                            detail = api.order(_pick(item, ("id",)) or "")
                            nfahub_order_id = str(_pick(detail, ORDER_ID_KEYS) or "")
                            creds2 = extract_credentials(detail)
                            if creds2 and not credentials:
                                credentials = creds2
                        except Exception:  # noqa: BLE001 - optional enrichment
                            pass
                    print(f"  order #{order.id}: recovered {len(credentials)} account(s) "
                          f"from NFAHub order {nfahub_order_id or '(id unknown)'}")
                    break

            # (b) Nothing to recover — buy now if allowed.
            if not credentials and args.buy_missing:
                credentials, nfahub_order_id, err = try_nfahub(order, product, tier)
                if err:
                    print(f"  order #{order.id}: buy failed: {err}")
                    continue

            if not credentials:
                print(f"  order #{order.id}: no matching NFAHub order and --buy-missing "
                      "not given — run again with --buy-missing to purchase now.")
                continue

            created = []
            for kv in credentials:
                db.session.add(Key(user_id=order.user_id, order_id=order.id,
                                   product_id=product.id, tier_id=tier.id,
                                   key_value=kv, expires_at=None, is_active=True,
                                   is_subscription=False,
                                   nfahub_order_id=nfahub_order_id or None))
                created.append(None)
            db.session.commit()
            created = Key.query.filter_by(order_id=order.id).all()
            order.status = "completed"
            db.session.commit()
            if nfahub_order_id:
                used_nfahub_ids.add(nfahub_order_id)
            _notify_buyer(order, product, tier, created)
            print(f"  order #{order.id}: DELIVERED {len(created)} account(s), buyer emailed.")
            repaired += 1

        print(f"\nDone. {repaired} order(s) repaired.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
