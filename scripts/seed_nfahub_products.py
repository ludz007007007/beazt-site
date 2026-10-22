"""Seed the NFAHub account storefront: one product per game, tiers per variant.

Creates/updates the five NFA account products (ARC Raiders, CS2, DayZ, Rust,
Wardogs) with pricing tiers for every NFAHub variant, converted from EUR to
GBP. Accounts never expire (duration_days=0, fulfillment sets no expiry) and
fulfil via the NFAHub reseller API (utils/nfahub.py) using the tier's
nfahub_variant_id.

Run inside the app environment:
    python scripts/seed_nfahub_products.py [--markup 1.0] [--api-key KEY]

Pricing: EUR cents from the catalog below are converted with the live EUR->GBP
rate (fallback 0.86) times --markup, rounded UP to the nearest 5p so a price
never sells below supplier cost. --markup 1.0 (default) is cost price — add
margin with e.g. --markup 2.5.

If NFAHUB_API_KEY (env or --api-key) is set, the script also fetches the live
GET /catalog and binds each tier's nfahub_variant_id by name match so
purchases fulfil automatically. Without a key, products are seeded with
prices only and variants must be bound later (admin tier editor).
"""

import argparse
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db, Product, PricingTier  # noqa: E402

# (game, product_slug, product_name, [(tier_label, nfahub_catalog_name, euro_cents, stock)])
NFA_CATALOG = [
    ("ARC Raiders", "nfahub-arc-raiders", "ARC Raiders NFA Accounts", [
        ("300+ hours", "ARC Raiders account with 300+ hours", 204, 0),
        ("200-300 hours", "ARC Raiders account with 200 - 300 hours", 183, 0),
        ("100-200 hours", "ARC Raiders account with 100 - 200 hours", 123, 0),
        ("0-100 hours", "ARC Raiders account with 0 - 100 hours", 98, 38),
    ]),
    ("Counter-Strike 2", "nfahub-cs2", "CS2 NFA Accounts", [
        ("Prime Account", "CS2 Prime Account", 64, 177),
        ("Premier Ready", "CS2 Premier Ready", 72, 181),
        ("5+ Medals", "CS2 5+ Medals", 106, 43),
        ("8+ Medals", "CS2 8+ Medals", 94, 9),
        ("Premier Rating", "CS2 Premier Rating", 81, 29),
        ("15,000+ Rating", "CS2 15,000+ Rating", 157, 3),
        ("20,000+ Rating", "CS2 20,000+ Rating", 123, 2),
        ("$100+ Inventory", "CS2 $100+ Inventory", 153, 0),
        ("Knife / Glove", "CS2 Knife / Glove", 213, 0),
    ]),
    ("DayZ", "nfahub-dayz", "DayZ NFA Accounts", [
        ("NFA Account", "DayZ NFA Account", 55, 1),
    ]),
    ("Rust", "nfahub-rust", "Rust NFA Accounts", [
        ("0-100 hours", "Rust account with 0 - 100 hours", 81, 160),
        ("100-200 hours", "Rust account with 100 - 200 hours", 115, 24),
        ("200-500 hours", "Rust account with 200 - 500 hours", 128, 22),
        ("500-1000 hours", "Rust account with 500 - 1000 hours", 145, 19),
        ("1000-1500 hours", "Rust account with 1000 - 1500 hours", 213, 0),
        ("1500-2000 hours", "Rust account with 1500 - 2000 hours", 102, 0),
        ("2000-5000 hours", "Rust account with 2000 - 5000 hours", 106, 0),
        ("5000+ hours", "Rust account with 5000+ hours", 115, 0),
        ("5+ Days Inactive", "Rust 5+ Days Inactive", 89, 0),
        ("Inactive 15+ Days", "Rust Inactive 15+ Days", 106, 0),
    ]),
    ("Wardogs", "nfahub-wardogs", "Wardogs NFA Accounts", [
        ("Temporary Account", "Wardogs Temporary Account", 60, 0),
    ]),
]

DESCRIPTION = (
    "Full-access {game} account, sourced through our NFAHub reseller account. "
    "Credentials are delivered to your BEAZT dashboard and email straight "
    "after payment. Multi-account orders ship as one bundle."
)

BUYER_NOTES = (
    "Delivered instantly after payment — no waiting on staff\n"
    "Account credentials appear under My Keys and are emailed to you\n"
    "Full account access; change the password on first login\n"
    "Issues with an account? Open a support ticket with your order number"
)

FEATURES = (
    "Instant automated delivery\n"
    "Full account access\n"
    "Stock checked live at purchase time\n"
    "Warranty handled via support tickets"
)

FALLBACK_EUR_GBP = 0.86


def _normalize_name(name):
    """Name-match key: lowercase alphanumerics only ('CS2 15,000+ Rating' -> 'cs215000rating')."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _eur_to_gbp_rate():
    """Live EUR->GBP rate with a safe fallback (checkout.py uses the same API)."""
    try:
        import requests
        resp = requests.get("https://open.er-api.com/v6/latest/EUR", timeout=5)
        rate = resp.json()["rates"]["GBP"]
        if 0.5 < float(rate) < 1.5:
            return float(rate)
    except Exception:
        pass
    return FALLBACK_EUR_GBP


def _gbp_pence(euro_cents, rate, markup):
    """Convert EUR cents to GBP pence, rounded UP to the nearest 5p."""
    return max(5, int(math.ceil(euro_cents * rate * markup / 5.0)) * 5)


def _live_variant_map(api_key):
    """Fetch GET /catalog and map normalized variant names to variant ids."""
    from utils.nfahub import NFAHub, iter_variants
    api = NFAHub(api_key=api_key)
    catalog = api.catalog()
    mapping = {}
    for row in iter_variants(catalog):
        name = _normalize_name(row.get("name"))
        if name and row.get("variant_id"):
            mapping[name] = (row["variant_id"], row.get("price_cents"))
    return mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markup", type=float, default=1.0,
                        help="Price multiplier over supplier cost (default 1.0 = cost price)")
    parser.add_argument("--api-key", default="",
                        help="NFAHub API key (falls back to NFAHUB_API_KEY env)")
    args = parser.parse_args()

    with app.app_context():
        api_key = args.api_key or os.getenv("NFAHUB_API_KEY", "")
        variant_map = {}
        if api_key:
            try:
                variant_map = _live_variant_map(api_key)
                print(f"NFAHub catalog synced: {len(variant_map)} live variants found.")
            except Exception as exc:  # noqa: BLE001 - seeding continues unbound
                print(f"WARNING: could not fetch NFAHub catalog ({exc}) — "
                      "tiers will be seeded without variant IDs.")
        else:
            print("NFAHUB_API_KEY not set — seeding prices only; bind variants later.")

        rate = _eur_to_gbp_rate()
        print(f"EUR->GBP rate: {rate:.4f} — markup: {args.markup}x")

        total_products = 0
        total_tiers = 0
        for game, slug, name, variants in NFA_CATALOG:
            product = Product.query.filter_by(slug=slug).first()
            if product is None:
                product = Product(
                    name=name,
                    slug=slug,
                    game=game,
                    visibility="public",
                    key_source="nfahub",
                    status="account",
                )
                db.session.add(product)
                db.session.flush()
                total_products += 1
                print(f"Created: {name}")
            else:
                product.game = product.game or game
                product.key_source = "nfahub"
                product.status = "account"
                print(f"Updated: {product.name}")

            product.description = product.description or DESCRIPTION.format(game=game)
            product.features_text = product.features_text or FEATURES
            product.buyer_notes = product.buyer_notes or BUYER_NOTES
            db.session.flush()

            for label, catalog_name, euro_cents, stock in variants:
                pence = _gbp_pence(euro_cents, rate, args.markup)
                tier = PricingTier.query.filter_by(product_id=product.id, label=label).first()
                if tier is None:
                    tier = PricingTier(
                        product_id=product.id,
                        label=label,
                        duration_days=0,
                        price_pence=pence,
                        is_subscription=False,
                        billing_type="one_time",
                        bundle_count=1,
                    )
                    db.session.add(tier)
                    db.session.flush()
                    total_tiers += 1
                tier.price_pence = pence
                tier.duration_days = 0
                tier.is_subscription = False
                tier.billing_type = "one_time"
                tier.bundle_count = 1
                if variant_map:
                    hit = variant_map.get(_normalize_name(catalog_name))
                    if hit:
                        tier.nfahub_variant_id = str(hit[0])
                        if hit[1]:
                            tier.price_pence = _gbp_pence(hit[1], rate, args.markup)
            db.session.commit()
            tiers = PricingTier.query.filter_by(product_id=product.id).all()
            bound = sum(1 for t in tiers if t.nfahub_variant_id)
            print(f"  {len(tiers)} tier(s), {bound} bound to live NFAHub variants: "
                  + ", ".join(f"{t.label}=£{t.price_pence / 100:.2f}" for t in tiers))

        print(f"\nDone: {total_products} product(s) created, {total_tiers} tier(s) added.")
        if not variant_map:
            print("Next step: set NFAHUB_API_KEY and re-run to bind variant IDs, "
                  "or paste them in Admin > Products > Tiers.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
