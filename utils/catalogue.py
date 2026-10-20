"""Storefront catalogue view-models.

One source of truth for what product cards show: status (fixed taxonomy),
freshness (DB dates only), prices, stock, ratings, and the honest site-wide
counts. Every value is derived from Product/PricingTier/Key/Review/Order/
StatusEvent rows; nothing here is hardcoded marketing copy.
"""

import zlib
from datetime import datetime

from sqlalchemy import func

from models import Key, Order, PricingTier, Product, Review, StatusEvent, db

STATUS_LABELS = {
    "undetected": "Undetected",
    "updating": "Updating",
    "risky": "Risky",
    "detected": "Detected",
    "down": "Down",
}
# Order used by the "featured" sort and the status filter select.
STATUS_ORDER = list(STATUS_LABELS)

_STATUS_ALIASES = {
    "online": "undetected",
    "offline": "updating",
    "maintenance": "updating",
}

SORT_OPTIONS = [
    ("featured", "Featured"),
    ("price_asc", "Price: low to high"),
    ("price_desc", "Price: high to low"),
    ("newest", "Recently updated"),
    ("name", "Name A–Z"),
]
_SORT_ALIASES = {"price-asc": "price_asc", "price-desc": "price_desc"}

# Order statuses that mean the buyer paid and the order went through.
DELIVERED_ORDER_STATUSES = ("completed", "paid", "delivered")


def normalize_status(raw_status):
    """Map admin/ChairFBI status values onto the storefront taxonomy."""
    s = (raw_status or "").strip().lower()
    if not s:
        return "undetected"  # column default for products never edited
    s = _STATUS_ALIASES.get(s, s)
    # An unrecognised value is never presented as safe.
    return s if s in STATUS_LABELS else "risky"


def normalize_status_filter(raw):
    s = (raw or "").strip().lower()
    s = _STATUS_ALIASES.get(s, s)
    return s if s in STATUS_LABELS else ""


def normalize_sort(raw):
    s = (raw or "").strip().lower()
    s = _SORT_ALIASES.get(s, s)
    return s if s in dict(SORT_OPTIONS) else "featured"


def format_date(value):
    """'15 Jan 2024' (no leading zero), or '' for None."""
    if not value:
        return ""
    return f"{value.day} {value.strftime('%b %Y')}"


def _latest_events(product_ids):
    if not product_ids:
        return {}
    latest = {}
    rows = (
        StatusEvent.query.filter(StatusEvent.product_id.in_(product_ids))
        .order_by(StatusEvent.created_at.desc())
        .all()
    )
    for ev in rows:
        latest.setdefault(ev.product_id, ev)
    return latest


def freshness(product, status, latest_event):
    """Freshness claim for a card, from DB timestamps only (never render time)."""
    verified = getattr(product, "last_verified_at", None)
    if verified:
        return {"text": f"Last verified {format_date(verified)}", "date": verified}
    if latest_event:
        if normalize_status(latest_event.status) == status:
            text = f"{STATUS_LABELS[status]} since {format_date(latest_event.created_at)}"
        else:
            text = f"Status changed {format_date(latest_event.created_at)}"
        return {"text": text, "date": latest_event.created_at}
    return {"text": "Not yet verified", "date": None}


def _pool_counts(product_ids):
    """Unassigned pool keys per product (same definition as the admin panel)."""
    if not product_ids:
        return {}
    rows = (
        db.session.query(Key.product_id, func.count(Key.id))
        .filter(Key.product_id.in_(product_ids), Key.user_id.is_(None), Key.is_active.is_(False))
        .group_by(Key.product_id)
        .all()
    )
    return dict(rows)


def plan_rows(tiers):
    """Purchase-panel ladder rows for the product page.

    Each row carries the explicit billing label ("one-time · N days" vs
    "recurring"), the per-day cost when it is meaningful, and the
    best-value flag on the cheapest per-day one-time plan (only when the
    buyer actually has a one-time choice to make). All maths derives from
    the tier rows — never rounded marketing numbers.
    """
    rows = [
        {
            "tier": t,
            "recurring": t.billing_type == "subscription",
            "per_day": None,
            "is_best": False,
        }
        for t in tiers
    ]
    for row in rows:
        if not row["recurring"] and row["tier"].duration_days:
            row["per_day"] = row["tier"].price_pounds / row["tier"].duration_days
    priced = [r for r in rows if r["per_day"] is not None]
    if len(priced) > 1:
        best = min(priced, key=lambda r: r["per_day"])
        best["is_best"] = True
    return rows


def _tiers_by_product(product_ids):
    out = {pid: [] for pid in product_ids}
    if product_ids:
        for t in (
            PricingTier.query.filter(PricingTier.product_id.in_(product_ids))
            .order_by(PricingTier.price_pence)
            .all()
        ):
            out[t.product_id].append(t)
    return out


def review_summaries(product_ids):
    """Approved-review aggregates keyed by product_id (absent = no rating shown)."""
    if not product_ids:
        return {}
    rows = (
        db.session.query(Review.product_id, func.count(Review.id), func.avg(Review.rating))
        .filter(Review.product_id.in_(product_ids), Review.status == "approved")
        .group_by(Review.product_id)
        .all()
    )
    return {pid: {"count": n, "avg": round(float(avg), 1)} for pid, n, avg in rows if n}


def build_cards(products, resolve_status=None):
    """Card view-models for `products`.

    `resolve_status(product)` may return a live status (e.g. ChairFBI); when
    it returns None the admin-set `product.status` is used.
    """
    ids = [p.id for p in products]
    summaries = review_summaries(ids)
    events = _latest_events(ids)
    tiers_by_product = _tiers_by_product(ids)
    pools = _pool_counts(ids)
    cards = []
    for p in products:
        tiers = tiers_by_product.get(p.id, [])
        live = resolve_status(p) if resolve_status else None
        status = normalize_status(live or p.status)
        # Only pool-fulfilled products can run out; other sources are not stock-bound.
        pool = pools.get(p.id, 0) if p.key_source == "pool" else None
        out_of_stock = pool == 0 and bool(tiers)
        # Availability badge key for every surface (private > sold out > pool
        # stock) — one derivation, so the product page, catalogue card and
        # status board can never disagree. Non-pool products carry no claim.
        if p.visibility == "private":
            availability = "private"
        elif out_of_stock:
            availability = "sold_out"
        elif p.key_source == "pool":
            availability = "in_stock"
        else:
            availability = None
        summary = summaries.get(p.id, {})
        cards.append({
            "product": p,
            "slug": p.slug,
            "name": p.name,
            "game": p.display_game,
            "game_slug": p.game_slug or "other",
            "is_private": p.visibility == "private",
            "featured": bool(getattr(p, "is_featured", False)),
            "status": status,
            "status_label": STATUS_LABELS[status],
            "availability": availability,
            "price_pence": tiers[0].price_pence if tiers else None,
            "price_pounds": tiers[0].price_pounds if tiers else None,
            "tier_count": len(tiers),
            "review_count": summary.get("count", 0),
            "review_avg": summary.get("avg"),
            "out_of_stock": out_of_stock,
            "updated_at": p.updated_at or p.created_at,
            "freshness": freshness(p, status, events.get(p.id)),
        })
    return cards


def sort_cards(cards, sort):
    """Sort in place; returns the normalised sort key actually applied."""
    sort = normalize_sort(sort)
    if sort == "price_asc":
        cards.sort(key=lambda c: (c["price_pence"] is None, c["price_pence"] or 0))
    elif sort == "price_desc":
        cards.sort(key=lambda c: (c["price_pence"] is None, -(c["price_pence"] or 0)))
    elif sort == "newest":
        cards.sort(key=lambda c: c["updated_at"] or datetime.min, reverse=True)
    elif sort == "name":
        cards.sort(key=lambda c: c["name"].lower())
    else:
        # Admin-pinned featured products lead, then private builds, then the
        # safest statuses. Stable on the incoming newest-first order.
        cards.sort(key=lambda c: (
            not c["featured"],
            not c["is_private"],
            STATUS_ORDER.index(c["status"]),
        ))
    return sort


def filter_cards(cards, q="", game="", status=""):
    q = (q or "").strip().lower()
    game = (game or "").strip().lower()
    status = normalize_status_filter(status)
    out = cards
    if q:
        out = [
            c for c in out
            if q in c["name"].lower()
            or q in c["game"].lower()
            or q in (c["product"].description or "").lower()
        ]
    if game:
        out = [c for c in out if c["game_slug"] == game]
    if status:
        out = [c for c in out if c["status"] == status]
    return out


def group_games(cards):
    """One entry per game (first-seen order) with DB-derived counts."""
    games = {}
    for c in cards:
        g = games.setdefault(c["game_slug"], {
            "slug": c["game_slug"], "name": c["game"], "cards": [],
        })
        g["cards"].append(c)
    out = []
    for g in games.values():
        prices = [c["price_pounds"] for c in g["cards"] if c["price_pounds"] is not None]
        counts = {}
        for c in g["cards"]:
            counts[c["status"]] = counts.get(c["status"], 0) + 1
        g["count"] = len(g["cards"])
        g["undetected"] = counts.get("undetected", 0)
        g["price_min"] = min(prices) if prices else None
        g["tier_count"] = sum(c["tier_count"] for c in g["cards"])
        # One segment per product, safest first — the honest per-game
        # "status accent" used by game cards and landing heroes.
        g["segments"] = [
            (c["status"], STATUS_LABELS[c["status"]])
            for c in sorted(g["cards"], key=lambda c: STATUS_ORDER.index(c["status"]))
        ]
        g["status_counts"] = [
            (key, STATUS_LABELS[key], counts[key])
            for key in STATUS_ORDER if counts.get(key)
        ]
        g["status_summary"] = ", ".join(
            f"{n} {label.lower()}" for _key, label, n in g["status_counts"]
        )
        # Deterministic per-game motif variant for the landing-page art
        # treatment (same slug -> same art, no render-time randomness).
        g["motif"] = zlib.crc32(g["slug"].encode("utf-8")) % 4
        out.append(g)
    return out


def honest_stats():
    """Site-wide counts straight from the DB. Templates hide zero values."""
    try:
        orders = Order.query.filter(Order.status.in_(DELIVERED_ORDER_STATUSES)).count()
        n_reviews, avg = (
            db.session.query(func.count(Review.id), func.avg(Review.rating))
            .filter(Review.status == "approved")
            .one()
        )
        products = Product.query.count()
    except Exception:  # noqa: BLE001 - a stats failure must never break a page
        db.session.rollback()
        return {"orders_delivered": 0, "review_count": 0, "rating_avg": None, "product_count": 0}
    return {
        "orders_delivered": orders,
        "review_count": n_reviews or 0,
        "rating_avg": round(float(avg), 1) if n_reviews else None,
        "product_count": products,
    }
