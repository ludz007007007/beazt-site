"""Populate the LOCAL development database with realistic demo data.

Usage (from the repo root, Windows):
    .venv\\Scripts\\python.exe scripts\\seed_demo.py

Creates (idempotently, safe to re-run): 5 demo products across Rust,
Counter-Strike 2 and Apex Legends with one-time and subscription tiers,
statuses undetected/updating/detected with StatusEvent history, unassigned
key-pool entries, demo users (admin + buyers), sample orders and reviews
(approved, pending, rejected). It also copies the synthetic PAYFAST_* values
from .env into empty Settings rows so local checkout has merchant config.

Demo logins (local only):
    admin  demo_admin / DemoAdmin!2026
    buyer  demo_buyer / DemoBuyer!2026

Refuses to run when DATABASE_URL looks like a production database or a
production environment marker (VERCEL=1, FLASK_ENV/APP_ENV=production) is set.
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEMO_ADMIN = ("demo_admin", "DemoAdmin!2026", "demo-admin@beazt.local")
DEMO_BUYER = ("demo_buyer", "DemoBuyer!2026", "demo-buyer@beazt.local")
DEMO_BUYER_2 = ("demo_buyer2", "DemoBuyer2!2026", "demo-buyer2@beazt.local")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_PROD_WORD = re.compile(r"(?<![a-z])prod(uction)?(?![a-z])")

# (slug, name, game, status, description, features, tiers, pool keys per one-time tier, history)
# tiers: (label, days, price_pence, is_subscription)
# history: [(days_ago, status, note)], oldest first; the last entry is the current status.
# "gallery" (optional): multi-image gallery shown in the product page's
# thumbnail strip. Generated cover URLs are the sanctioned demo media.
DEMO_PRODUCTS = [
    {
        "slug": "rust-esp-lite",
        "name": "Rust ESP Lite",
        "game": "Rust",
        "visibility": "public",
        "description": "Lightweight external ESP for Rust: players, sleepers and resources with configurable ranges.",
        "features": "Player and sleeper ESP\nResource and loot overlays\nConfigurable render distance\nStream-safe overlay mode",
        "requirements": "Windows 10/11 64-bit\nIntel or AMD CPU\nNo USB required",
        "tiers": [("1 Day", 1, 500, False), ("1 Week", 7, 1800, False), ("1 Month", 30, 3900, False)],
        "pool_keys": 6,
        "history": [(45, "undetected", "Initial release verified on current game build")],
        "gallery": [
            "/cheat-image/rust-esp-lite",
            "/cheat-image/rust-esp-lite?v=1",
            "/cheat-image/rust-esp-lite?v=2",
        ],
    },
    {
        "slug": "rust-full-suite",
        "name": "Rust Full Suite",
        "game": "Rust",
        "visibility": "public",
        "description": "Full external suite for Rust with aim assistance presets, ESP and radar.",
        "features": "Aim assistance with smoothing presets\nFull ESP and 2D radar\nItem and raid-base markers\nPer-weapon configs",
        "requirements": "Windows 10/11 64-bit\nIntel or AMD CPU\nSecure Boot off",
        "tiers": [("Weekly", 7, 2400, True), ("Monthly", 30, 6900, True), ("Lifetime", 3650, 29900, False)],
        "pool_keys": 3,
        "history": [
            (60, "undetected", "Verified on current game build"),
            (2, "updating", "Game update released; build being updated and re-tested"),
        ],
    },
    {
        "slug": "cs2-legit-assist",
        "name": "CS2 Legit Assist",
        "game": "Counter-Strike 2",
        "visibility": "public",
        "description": "Legit-focused assistance for Counter-Strike 2 with humanised aim curves and triggerbot.",
        "features": "Humanised aim curves\nTriggerbot with reaction delay\nGlow and box ESP\nSpectator list",
        "requirements": "Windows 10/11 64-bit\nIntel or AMD CPU\nNo USB required",
        "tiers": [("1 Day", 1, 400, False), ("1 Month", 30, 3500, False), ("Monthly", 30, 3200, True)],
        "pool_keys": 5,
        "gallery": [
            "/cheat-image/cs2-legit-assist",
            "/cheat-image/cs2-legit-assist?v=1",
        ],
        "history": [
            (90, "undetected", "Initial release verified"),
            (30, "updating", "Updated for CS2 engine patch"),
            (29, "undetected", "Re-verified after update"),
        ],
    },
    {
        "slug": "cs2-rage-suite",
        "name": "CS2 Rage Suite",
        "game": "Counter-Strike 2",
        "visibility": "public",
        "description": "Rage configuration suite for Counter-Strike 2. Currently detected; purchases paused until a fix ships.",
        "features": "Rage aimbot\nAnti-aim presets\nFull ESP",
        "requirements": "Windows 10/11 64-bit\nIntel CPU only",
        "tiers": [("1 Week", 7, 2000, False), ("1 Month", 30, 5500, False)],
        "pool_keys": 0,
        "history": [
            (120, "undetected", "Initial release verified"),
            (5, "detected", "Detection wave reported; sales paused while a fix is built"),
        ],
    },
    {
        "slug": "apex-esp",
        "name": "Apex ESP",
        "game": "Apex Legends",
        "visibility": "public",
        "description": "External ESP for Apex Legends with item filtering and team-safe overlays.",
        "features": "Player ESP with health and shields\nItem filter by rarity\nTeam-safe overlay",
        "requirements": "Windows 10/11 64-bit\nIntel or AMD CPU\nSpoofer recommended",
        "tiers": [("1 Day", 1, 600, False), ("1 Week", 7, 2200, False), ("Monthly", 30, 4500, True)],
        "pool_keys": 4,
        "history": [(20, "undetected", "Verified on current season build")],
    },
]

# (session id, buyer, product slug, tier label, status, days ago, quantity)
DEMO_ORDERS = [
    ("demo-order-001", DEMO_BUYER, "rust-esp-lite", "1 Month", "completed", 12, 1),
    ("demo-order-002", DEMO_BUYER, "cs2-legit-assist", "1 Day", "completed", 6, 1),
    ("demo-order-003", DEMO_BUYER, "apex-esp", "1 Week", "pending", 1, 1),
    ("demo-order-004", DEMO_BUYER_2, "rust-esp-lite", "1 Week", "completed", 20, 1),
    ("demo-order-005", DEMO_BUYER_2, "rust-full-suite", "Lifetime", "awaiting_keys", 3, 1),
    # Gives demo_buyer a third state on /my-keys: a completed order whose key
    # was later revoked while time remained (distinct from a natural expiry).
    ("demo-order-006", DEMO_BUYER, "rust-esp-lite", "1 Month", "completed", 25, 1),
]

# (order session id, chairfbi key id) — completed demo orders whose key was
# revoked after delivery. Powers the Revoked card + "License ID" meta demo.
DEMO_REVOKED_KEYS = [("demo-order-006", "chairfbi-demo-8f42")]

# (order session id, rating, title, body, status)
DEMO_REVIEWS = [
    ("demo-order-001", 5, "Smooth setup", "Key arrived in My Keys right after payment and the loader guide covered everything.", "approved"),
    ("demo-order-002", 4, "Solid legit config", "Aim curves feel natural. Took a minute to tune smoothing for my sensitivity.", "approved"),
    ("demo-order-004", 5, "Good overlays", "Resource ESP is clean and the stream-safe mode works with OBS.", "approved"),
    ("demo-order-005", 3, "Waiting on key", "Payment went through, waiting for the key to be issued.", "pending"),
]
DEMO_REJECTED_REVIEW = ("demo_buyer2", "cs2-rage-suite", 1, "asdf", "spam spam spam", "rejected")


def check_database_url(url, env=None):
    """Return (ok, reason). Only local SQLite or localhost databases are allowed."""
    env = os.environ if env is None else env
    for var in ("FLASK_ENV", "APP_ENV", "ENV"):
        if (env.get(var) or "").strip().lower() in ("prod", "production"):
            return False, f"{var}={env.get(var)} marks this as a production environment"
    if (env.get("VERCEL") or "").strip() == "1":
        return False, "VERCEL=1 marks this as a production deployment"

    if not url:
        return True, "default local SQLite database"

    parts = urlsplit(url)
    scheme = parts.scheme.split("+")[0].lower()
    if scheme == "sqlite":
        target = url.split(":", 1)[1].lower()
        if _PROD_WORD.search(target):
            return False, "SQLite path looks like a production database"
        return True, "local SQLite database"

    host = (parts.hostname or "").lower()
    if host not in _LOCAL_HOSTS:
        return False, f"database host '{host or '?'}' is not local"
    if _PROD_WORD.search((parts.path or "").lower()):
        return False, "database name looks like a production database"
    return True, "localhost database"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _demo_key(*parts):
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest().upper()
    return "DEMO-" + "-".join(digest[i:i + 4] for i in range(0, 16, 4))


def _upsert_user(db, User, username, password, email, is_admin):
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, email=email, is_admin=is_admin, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
    return user


def _seed_product(db, models, spec):
    Product, PricingTier, Key, StatusEvent = models
    now = _now()
    product = Product.query.filter_by(slug=spec["slug"]).first()
    if product is None:
        product = Product(
            slug=spec["slug"],
            name=spec["name"],
            game=spec["game"],
            description=spec["description"],
            features_text=spec["features"],
            buyer_notes=spec["requirements"],
            key_source="pool",
            visibility=spec["visibility"],
            # No shared placeholder image: the typographic cover generator
            # (/cheat-image/<slug>) is the per-game fallback.
            image_url=None,
            created_at=now - timedelta(days=spec["history"][0][0]),
        )
        db.session.add(product)
        db.session.flush()
    else:
        # Migrate pre-existing demo rows off the old shared placeholder.
        if product.image_url == "/static/icons/rust_placeholder.jpg":
            product.image_url = None

    # Art direction: selected demo products carry a multi-image gallery so
    # the product page's thumbnail strip is browser-verifiable. Never
    # overwrite a gallery that was set deliberately.
    gallery = spec.get("gallery")
    if gallery and not (product.gallery_images or "").strip():
        product.gallery_images = json.dumps(gallery)

    for label, days, price, is_sub in spec["tiers"]:
        tier = PricingTier.query.filter_by(product_id=product.id, label=label).first()
        if tier is None:
            tier = PricingTier(
                product_id=product.id,
                label=label,
                duration_days=days,
                price_pence=price,
                is_subscription=is_sub,
                billing_type="subscription" if is_sub else "one_time",
                ivno_subscription_link=(
                    f"https://ivno.invalid/subscribe/demo-{spec['slug']}-{days}d" if is_sub else None
                ),
            )
            db.session.add(tier)
            db.session.flush()
        if not is_sub:
            for n in range(spec["pool_keys"]):
                value = _demo_key("pool", spec["slug"], label, n)
                # Unassigned pool stock is user_id=None + is_active=False: the
                # definition checkout and the admin pool counts use.
                key = Key.query.filter_by(key_value=value).first()
                if key is None:
                    db.session.add(Key(product_id=product.id, tier_id=tier.id, key_value=value, is_active=False))
                elif key.user_id is None and key.is_active:
                    key.is_active = False

    for days_ago, status, note in spec["history"]:
        exists = StatusEvent.query.filter_by(product_id=product.id, status=status, note=note).first()
        if exists is None:
            db.session.add(StatusEvent(
                product_id=product.id, status=status, note=note,
                created_at=now - timedelta(days=days_ago),
            ))
    product.status = spec["history"][-1][1]
    if product.updated_at is None:
        product.updated_at = now - timedelta(days=spec["history"][-1][0])
    return product


def _backfill_status_events(db, Product, StatusEvent):
    """Give every product (incl. non-demo ones) at least one event matching its current status."""
    now = _now()
    for product in Product.query.all():
        latest = (StatusEvent.query.filter_by(product_id=product.id)
                  .order_by(StatusEvent.created_at.desc()).first())
        if latest is None or latest.status != (product.status or "undetected"):
            db.session.add(StatusEvent(
                product_id=product.id,
                status=product.status or "undetected",
                note="Status recorded",
                created_at=product.updated_at or product.created_at or now,
            ))


def _seed_orders(db, User, Product, PricingTier, Order, Key):
    now = _now()
    for session_id, buyer, slug, tier_label, status, days_ago, qty in DEMO_ORDERS:
        if Order.query.filter_by(stripe_session_id=session_id).first() is not None:
            continue
        user = User.query.filter_by(username=buyer[0]).first()
        product = Product.query.filter_by(slug=slug).first()
        tier = PricingTier.query.filter_by(product_id=product.id, label=tier_label).first()
        created = now - timedelta(days=days_ago)
        order = Order(
            user_id=user.id, tier_id=tier.id, stripe_session_id=session_id,
            status=status, quantity=qty, created_at=created,
        )
        db.session.add(order)
        db.session.flush()
        if status == "completed":
            db.session.add(Key(
                user_id=user.id, order_id=order.id, product_id=product.id, tier_id=tier.id,
                key_value=_demo_key("order", session_id), assigned_at=created,
                expires_at=created + timedelta(days=tier.duration_days), is_active=True,
                is_subscription=bool(tier.is_subscription), created_at=created,
            ))
    # Idempotent revoke pass: flips the flagged demo keys to is_active=False
    # (and stamps their ChairFBI id) without touching anything else.
    for session_id, chairfbi_id in DEMO_REVOKED_KEYS:
        key = Key.query.filter_by(key_value=_demo_key("order", session_id)).first()
        if key is not None and (key.is_active or key.chairfbi_key_id != chairfbi_id):
            key.is_active = False
            key.chairfbi_key_id = chairfbi_id


def _seed_reviews(db, User, Product, Order, Review):
    now = _now()
    for session_id, rating, title, body, status in DEMO_REVIEWS:
        order = Order.query.filter_by(stripe_session_id=session_id).first()
        if order is None or Review.query.filter_by(order_id=order.id).first() is not None:
            continue
        created = order.created_at + timedelta(days=1)
        db.session.add(Review(
            user_id=order.user_id, product_id=order.tier.product_id, order_id=order.id,
            rating=rating, title=title, body=body, status=status,
            created_at=min(created, now),
            approved_at=min(created, now) if status == "approved" else None,
        ))

    username, slug, rating, title, body, status = DEMO_REJECTED_REVIEW
    user = User.query.filter_by(username=username).first()
    product = Product.query.filter_by(slug=slug).first()
    if Review.query.filter_by(user_id=user.id, product_id=product.id, title=title).first() is None:
        db.session.add(Review(
            user_id=user.id, product_id=product.id, rating=rating, title=title,
            body=body, status=status, created_at=now - timedelta(days=4),
        ))


def _seed_settings(Setting):
    for setting_key, env_key in (
        ("payfast_merchant_id", "PAYFAST_MERCHANT_ID"),
        ("payfast_merchant_key", "PAYFAST_MERCHANT_KEY"),
        ("payfast_passphrase", "PAYFAST_PASSPHRASE"),
        ("payfast_item_name", "PAYFAST_ITEM_NAME"),
    ):
        value = (os.getenv(env_key) or "").strip()
        if value and not Setting.get(setting_key):
            Setting.set(setting_key, value)


def seed_demo_data():
    """Create/refresh demo data. Must run inside an app context. Returns row counts."""
    from models import Key, Order, PricingTier, Product, Review, Setting, StatusEvent, User, db

    _upsert_user(db, User, DEMO_ADMIN[0], DEMO_ADMIN[1], DEMO_ADMIN[2], True)
    _upsert_user(db, User, DEMO_BUYER[0], DEMO_BUYER[1], DEMO_BUYER[2], False)
    _upsert_user(db, User, DEMO_BUYER_2[0], DEMO_BUYER_2[1], DEMO_BUYER_2[2], False)

    for spec in DEMO_PRODUCTS:
        _seed_product(db, (Product, PricingTier, Key, StatusEvent), spec)
    db.session.flush()
    _backfill_status_events(db, Product, StatusEvent)
    # Art direction: no product may keep the old shared Rust placeholder —
    # the typographic cover generator is the fallback for every product.
    for product in Product.query.filter_by(image_url="/static/icons/rust_placeholder.jpg").all():
        product.image_url = None
    db.session.flush()
    _seed_orders(db, User, Product, PricingTier, Order, Key)
    db.session.flush()
    _seed_reviews(db, User, Product, Order, Review)
    db.session.commit()
    _seed_settings(Setting)

    return {m.__name__: m.query.count() for m in (Product, PricingTier, Key, User, Order, Review, StatusEvent)}


def main():
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
    url = os.getenv("DATABASE_URL")
    ok, reason = check_database_url(url)
    if not ok:
        print(f"REFUSING to seed demo data: {reason}. This script is for local development only.")
        return 2

    from app import app

    with app.app_context():
        counts = seed_demo_data()
    print(f"Demo data seeded ({reason}).")
    print("Row counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"Demo admin: {DEMO_ADMIN[0]} / {DEMO_ADMIN[1]}")
    print(f"Demo buyer: {DEMO_BUYER[0]} / {DEMO_BUYER[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
