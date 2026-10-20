from pathlib import Path
import json
import time
import threading
import logging
from datetime import datetime

from flask import Blueprint, render_template, abort, current_app, Response, redirect, request, url_for, flash, session
from flask_login import login_required, current_user
from models import db, Product, Key, PricingTier, User, Order, Review
from config import get_loader_config, get_discord_config, get_ivno_config
from utils import catalogue, covers
from utils.passwords import password_error

main_bp = Blueprint("main", __name__)
logger = logging.getLogger(__name__)


def _admin_or_deny():
    """VAL-SEC-001: health/diagnostic endpoints must never leak to non-admins.

    Anonymous requests are redirected to login; authenticated non-admins get
    403. Returns True when the caller may see the full payload.
    """
    if not current_user.is_authenticated:
        return False, redirect(url_for("auth.login"))
    if not current_user.is_admin:
        return False, abort(403)
    return True, None


def get_product_features(slug):
    feature_sets = {
        "rust-external-private": {
            "label": "Rust External - BeaZt Legit",
            "items": [
                "Legit ESP suite",
                "Debug camera",
                "Player and resource overlays",
                "Distance and visibility tools",
                "Legit-focused presets",
                "Private build updates",
                "Discord setup support",
            ],
        },
    }
    default_set = {
        "label": "Game Access",
        "items": [
            "Core external toolkit",
            "Visualization modules",
            "Update maintenance",
            "Private support channel",
        ],
    }
    return feature_sets.get(slug, default_set)


def _get_product_features_from_db(product):
    items = []
    if product and product.features_text:
        items = [line.strip() for line in product.features_text.splitlines() if line.strip()]
    if not items:
        items = [
            "Core external toolkit with visual overlays",
            "Regular update maintenance included",
            "Private Discord support channel",
            "Configure features in Admin -> Tiers -> Product Content",
        ]
    return {
        "label": product.name if product else "Features",
        "items": items,
    }


@main_bp.route("/cheat-image/<slug>")
def cheat_image(slug):
    """Typographic product cover (SIGNAL art direction, utils/covers.py).

    Real media still wins when image_url is set and reachable; the generated
    per-game cover is the guaranteed fallback for cards, galleries and OG
    images. `?v=N` (0-3) shifts the motif framing so a product gallery can
    show several distinct typographic shots of the same product.
    """
    product = Product.query.filter_by(slug=slug).first()
    if not product:
        abort(404)

    if product.image_url:
        # Only redirect when the target actually exists: a set-but-broken
        # image_url would otherwise 404 at the redirect target and defeat
        # the card's data-fallback to this cover. External URLs cannot be
        # verified locally, so they keep the plain redirect.
        if product.image_url.startswith("/static/"):
            static_file = Path(current_app.root_path) / "static" / product.image_url[len("/static/"):]
            if static_file.is_file():
                return redirect(product.image_url)
            # Missing static file -> fall through to the generated cover.
        else:
            return redirect(product.image_url)

    status = catalogue.normalize_status(
        _get_chairfbi_cheat_status(product) or product.status
    )
    variant = max(0, min(request.args.get("v", 0, type=int), 3))
    png = covers.cover_png(
        product.display_game,
        product_name=product.name,
        status=status,
        variant=variant,
    )
    return Response(
        png,
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@main_bp.route("/game-image/<game_slug>")
def game_image(game_slug):
    """Per-game typographic cover for /games tiles and game-page OG images.

    The accent bar carries the game's dominant status — the status most of
    its products are in, ties resolving to the safer one — mirroring the
    ratio strip on the game cards.
    """
    products = [p for p in Product.query.all() if p.game_slug == game_slug]
    if not products:
        abort(404)
    counts = {}
    for p in products:
        s = catalogue.normalize_status(_get_chairfbi_cheat_status(p) or p.status)
        counts[s] = counts.get(s, 0) + 1
    dominant = min(counts, key=lambda s: (-counts[s], catalogue.STATUS_ORDER.index(s)))
    png = covers.cover_png(products[0].display_game, product_name=None, status=dominant)
    return Response(
        png,
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# --- ChairFBI live status ----------------------------------------------------
# The ChairFBI API is rate limited to 100 requests/minute per token. Catalogue,
# status, and product pages each render N products, so status must be fetched
# once per TTL window and shared — never once per product per render. A short
# negative cache also stops hammering the API (and stalling renders) when it's
# down or rate limited.
_CHAIRFBI_STATUS_TTL = 45      # seconds: fresh data window
_CHAIRFBI_ERROR_TTL = 20       # seconds: cool-down after a failed fetch
_chairfbi_status_cache = {"cheats": None, "fetched_at": 0.0, "error_until": 0.0}
_chairfbi_status_lock = threading.Lock()


def _fetch_chairfbi_status():
    """Return the live /api/status cheat list, shared via a TTL cache.

    One API call per window serves every product on the site. Returns None
    when the token is unconfigured or when the last fetch failed within the
    cool-down window (callers fall back to admin-set product status).
    """
    from config import get_chairfbi_config
    cfg = get_chairfbi_config()
    if not cfg.get("api_token"):
        return None

    now = time.time()
    with _chairfbi_status_lock:
        if (
            _chairfbi_status_cache["cheats"] is not None
            and now - _chairfbi_status_cache["fetched_at"] < _CHAIRFBI_STATUS_TTL
        ):
            return _chairfbi_status_cache["cheats"]
        if now < _chairfbi_status_cache["error_until"]:
            return None
        try:
            from utils.chairfbi import ChairFBI
            cf = ChairFBI(api_token=cfg["api_token"], base_url=cfg.get("api_base"))
            cheats = cf.get_cheats()
            if not isinstance(cheats, list):
                cheats = []
            _chairfbi_status_cache["cheats"] = cheats
            _chairfbi_status_cache["fetched_at"] = time.time()
            _chairfbi_status_cache["error_until"] = 0.0
            return cheats
        except Exception as exc:  # noqa: BLE001 - storefront must not break on API errors
            logger.warning("ChairFBI status fetch failed: %s", exc)
            _chairfbi_status_cache["error_until"] = time.time() + _CHAIRFBI_ERROR_TTL
            return None


_chairfbi_bases_cache = {"data": None, "fetched_at": 0.0, "error_until": 0.0}


def _fetch_chairfbi_bases():
    """Live /api/status-bases (cheat-base/loader status), TTL-cached.

    Returns a list of {id, name, enabled, status} dicts, or None when the
    integration is unconfigured or unavailable.
    """
    from config import get_chairfbi_config
    cfg = get_chairfbi_config()
    if not cfg.get("api_token"):
        return None

    now = time.time()
    with _chairfbi_status_lock:
        if (
            _chairfbi_bases_cache["data"] is not None
            and now - _chairfbi_bases_cache["fetched_at"] < _CHAIRFBI_STATUS_TTL
        ):
            return _chairfbi_bases_cache["data"]
        if now < _chairfbi_bases_cache["error_until"]:
            return None
        try:
            from utils.chairfbi import ChairFBI
            cf = ChairFBI(api_token=cfg["api_token"], base_url=cfg.get("api_base"))
            bases = cf.get_cheat_bases()
            if not isinstance(bases, list):
                bases = []
            _chairfbi_bases_cache["data"] = bases
            _chairfbi_bases_cache["fetched_at"] = time.time()
            _chairfbi_bases_cache["error_until"] = 0.0
            return bases
        except Exception as exc:  # noqa: BLE001
            logger.warning("ChairFBI base status fetch failed: %s", exc)
            _chairfbi_bases_cache["error_until"] = time.time() + _CHAIRFBI_ERROR_TTL
            return None


def _get_chairfbi_cheat_status(product):
    if not product:
        return None
    # Admin-set status takes priority
    if product.status and product.status not in ("undetected",):
        return product.status
    # Otherwise check the (cached) ChairFBI API status list
    if not product.chairfbi_cheat_id:
        return product.status or "undetected"
    cheats = _fetch_chairfbi_status()
    if cheats:
        for c in cheats:
            cid = str(c.get("id", ""))
            cname = c.get("name", "")
            if cid == product.chairfbi_cheat_id or cname == product.chairfbi_cheat_id:
                return "online" if c.get("active") else "offline"
    return None


def _get_product_gallery(slug, product=None):
    images = []

    if product and product.gallery_images:
        try:
            import json
            vc_images = json.loads(product.gallery_images)
            if isinstance(vc_images, list):
                images.extend(vc_images)
        except (json.JSONDecodeError, TypeError):
            pass

    gallery_dir = Path(current_app.root_path) / "static" / "images" / "products" / slug
    if gallery_dir.exists() and gallery_dir.is_dir():
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".avif"}
        for file_path in sorted(gallery_dir.iterdir()):
            if file_path.suffix.lower() in allowed:
                images.append(f"/static/images/products/{slug}/{file_path.name}")

    if not images and product and product.image_url:
        images.append(product.image_url)
    elif not images and product is None:
        pass

    return images


# --- Catalogue ---------------------------------------------------------------
# View-models live in utils/catalogue.py; routes only choose the product set.

def _catalog_cards(products):
    return catalogue.build_cards(products, resolve_status=_get_chairfbi_cheat_status)


def _all_cards():
    # Newest first: freshly added products surface first within equal ranks.
    return _catalog_cards(Product.query.order_by(Product.created_at.desc()).all())


def _user_can_review(product, user_id):
    """Verified buyer = completed order for a tier of this product, or an
    active key assigned to them (covers admin-assigned pool keys)."""
    has_completed_order = (
        Order.query.join(PricingTier, Order.tier_id == PricingTier.id)
        .filter(
            Order.user_id == user_id,
            PricingTier.product_id == product.id,
            Order.status == "completed",
        )
        .first()
    )
    if has_completed_order:
        return True
    return (
        Key.query.filter_by(
            user_id=user_id, product_id=product.id, is_active=True
        ).first()
        is not None
    )


def _apply_catalogue_filters(cards, q, game, status):
    """Filter catalogue cards by free-text query, game slug, and status."""
    q = (q or "").strip().lower()
    game = (game or "").strip().lower()
    status = (status or "").strip().lower()
    out = cards
    if q:
        out = [
            c for c in out
            if q in c["name"].lower() or q in c["game"].lower()
            or (c["product"].description or "").lower().find(q) >= 0
        ]
    if game:
        out = [c for c in out if c["game_slug"] == game]
    if status in ("online", "maintenance", "updating"):
        out = [c for c in out if c["status"] == status]
    return out


@main_bp.route("/")
def index():
    cards = _all_cards()
    catalogue.sort_cards(cards, "featured")
    total = len(cards)
    # The homepage previews the catalogue; /cheats is the full, filterable
    # list. Always show fewer cards than exist so the two never duplicate.
    showcase = cards[: min(3, max(total - 1, 1))] if total else []
    games = catalogue.group_games(cards)
    status_counts = [
        (key, catalogue.STATUS_LABELS[key], n)
        for key in catalogue.STATUS_ORDER
        if (n := sum(1 for c in cards if c["status"] == key))
    ]

    latest_reviews = (
        Review.query.filter_by(status="approved")
        .order_by(Review.created_at.desc())
        .limit(3)
        .all()
    )
    return render_template(
        "index.html",
        showcase=showcase,
        total_products=total,
        games=games,
        status_counts=status_counts,
        latest_reviews=latest_reviews,
    )


@main_bp.route("/cheats")
def cheats():
    all_cards = _all_cards()
    filters = {
        "q": (request.args.get("q") or "").strip()[:100],
        "game": (request.args.get("game") or "").strip().lower(),
        "status": catalogue.normalize_status_filter(request.args.get("status")),
    }
    games = catalogue.group_games(all_cards)
    cards = catalogue.filter_cards(all_cards, **filters)
    sort = catalogue.sort_cards(cards, request.args.get("sort"))
    return render_template(
        "cheats.html",
        cards=cards,
        total=len(all_cards),
        games=games,
        filters=filters,
        sort=sort,
        sort_options=catalogue.SORT_OPTIONS,
        status_options=[(k, catalogue.STATUS_LABELS[k]) for k in catalogue.STATUS_ORDER],
        filtered=bool(filters["q"] or filters["game"] or filters["status"] or sort != "featured"),
    )

@main_bp.route("/product/<slug>")
def product_detail(slug):
    product = Product.query.filter_by(slug=slug).first()
    if not product:
        abort(404)
    tiers = (
        PricingTier.query
        .filter_by(product_id=product.id)
        .order_by(PricingTier.duration_days)
        .all()
    )
    preselected_id = request.args.get("tier_id", type=int)
    selected_tier = None
    if preselected_id:
        selected_tier = next((t for t in tiers if t.id == preselected_id), None)
    if not selected_tier:
        selected_tier = next((t for t in tiers if t.duration_days == 30), tiers[0] if tiers else None)

    product_features = _get_product_features_from_db(product)
    cheat_status = _get_chairfbi_cheat_status(product)
    gallery_images = _get_product_gallery(product.slug, product=product)

    vc_specs = None
    vc_features = []
    vc_status = None
    vc_system_features = []
    vc_cap_names = {}
    if product.venomcheats_data:
        try:
            vc_data = json.loads(product.venomcheats_data)
            vc_specs = {
                'os': vc_data.get('operatingSystem', ''),
                'cpu': vc_data.get('processor', ''),
                'ac': vc_data.get('antiCheat', ''),
            }
            vc_features = vc_data.get('capabilities', [])
            vc_status = vc_data.get('status', '')
        except (json.JSONDecodeError, TypeError):
            pass

    try:
        from utils.venomcheats import CAPABILITY_NAMES, SYSTEM_FEATURES
        vc_cap_names = CAPABILITY_NAMES
        vc_system_features = SYSTEM_FEATURES
    except ImportError:
        pass

    variants = []
    for t in tiers:
        variants.append({
            "id": t.id,
            "label": t.label,
            "duration_days": t.duration_days,
            "price_pence": t.price_pence,
            "price_pounds": t.price_pounds,
            "billing_type": t.billing_type,
            "subscription_link": t.ivno_subscription_link or "",
        })

    # Verified reviews: approved only, aggregated only when at least one exists.
    reviews = (
        Review.query.filter_by(product_id=product.id, status="approved")
        .order_by(Review.created_at.desc())
        .all()
    )
    review_avg = (
        round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else None
    )
    can_review = (
        current_user.is_authenticated
        and not Review.query.filter_by(
            user_id=current_user.id, product_id=product.id
        ).first()
        and _user_can_review(product, current_user.id)
    )

    # Other products in the same game, for the "more in <game>" strip.
    related_cards = []
    if product.game:
        same_game = Product.query.filter(
            Product.game == product.game, Product.id != product.id
        ).order_by(Product.created_at.desc()).all()
        related_cards = _catalog_cards(same_game)

    # Gateway availability for the purchase panel: an unconfigured IVNO
    # gateway renders the card option disabled up front (checkout itself
    # still answers 503 {error, gateway_unavailable: true} for stale pages).
    ivno_configured = bool(get_ivno_config()["api_key"])

    # Card view-model (status taxonomy + freshness + availability) so the
    # product page shows exactly what the catalogue card shows for the same
    # product — one derivation, never a second vocabulary.
    card = _catalog_cards([product])[0]

    # OG image: first gallery shot or the generated cover, always absolute
    # (relative URLs are useless to social crawlers).
    og_image = (
        gallery_images[0] if gallery_images
        else url_for("main.cheat_image", slug=product.slug, _external=True)
    )
    if og_image.startswith("/"):
        og_image = request.url_root.rstrip("/") + og_image

    return render_template(
        "product.html",
        product=product,
        tiers=tiers,
        selected_tier=selected_tier,
        gallery_images=gallery_images,
        og_image=og_image,
        product_features=product_features,
        cheat_status=cheat_status,
        variants=variants,
        plan_rows=catalogue.plan_rows(tiers),
        card=card,
        ivno_configured=ivno_configured,
        vc_specs=vc_specs,
        vc_features=vc_features,
        vc_status=vc_status,
        vc_cap_names=vc_cap_names,
        vc_system_features=vc_system_features,
        reviews=reviews,
        review_avg=review_avg,
        can_review=can_review,
        related_cards=related_cards,
    )


@main_bp.route("/product/<slug>/review", methods=["POST"])
@login_required
def submit_review(slug):
    """Verified-buyer review submission (moderated before it appears)."""
    product = Product.query.filter_by(slug=slug).first()
    if not product:
        abort(404)
    product_url = url_for("main.product_detail", slug=slug) + "#reviews"
    if not _user_can_review(product, current_user.id):
        flash("Only verified buyers can review this product.", "error")
        return redirect(product_url)
    if Review.query.filter_by(user_id=current_user.id, product_id=product.id).first():
        flash("You have already reviewed this product.", "error")
        return redirect(product_url)

    rating = request.form.get("rating", type=int)
    title = (request.form.get("title") or "").strip()[:128]
    body = (request.form.get("body") or "").strip()
    if not rating or not (1 <= rating <= 5) or len(body) < 10:
        flash("Pick a 1-5 star rating and write at least 10 characters.", "error")
        return redirect(product_url)

    # Attach the fulfilled order that qualified the buyer, if any.
    qualifying_order = (
        Order.query.join(PricingTier, Order.tier_id == PricingTier.id)
        .filter(
            Order.user_id == current_user.id,
            PricingTier.product_id == product.id,
            Order.status == "completed",
        )
        .first()
    )
    review = Review(
        user_id=current_user.id,
        product_id=product.id,
        order_id=qualifying_order.id if qualifying_order else None,
        rating=rating,
        title=title or None,
        body=body,
        status="pending",
    )
    db.session.add(review)
    db.session.commit()
    flash("Thanks! Your review was submitted and appears once approved.", "success")
    return redirect(product_url)


@main_bp.route("/games")
def games_index():
    """Index of all games that have products (crawlable category hub)."""
    games = catalogue.group_games(_all_cards())
    return render_template("games.html", games=games)


@main_bp.route("/games/<game_slug>")
def game_page(game_slug):
    """Per-game landing page: every product for one game, server-rendered."""
    slug = game_slug.strip().lower()
    cards = [c for c in _all_cards() if c["game_slug"] == slug]
    if not cards:
        abort(404)
    catalogue.sort_cards(cards, "featured")
    game = catalogue.group_games(cards)[0]
    return render_template("game.html", game=game, cards=cards)


@main_bp.route("/status")
def status_page():
    """Full live status board: every product, real statuses only."""
    cards = _all_cards()
    undetected_count = sum(1 for c in cards if c["status"] == "undetected")
    last_verified = max(
        (c["freshness"]["date"] for c in cards if c["freshness"]["date"]), default=None
    )
    base_statuses = _fetch_chairfbi_bases()
    return render_template(
        "status.html",
        cards=cards,
        undetected_count=undetected_count,
        last_verified=last_verified,
        base_statuses=base_statuses,
    )

@main_bp.route("/sitemap.xml")
def sitemap():
    """XML sitemap: static pages, product pages, and game landing pages."""
    site_url = (current_app.config.get("SITE_URL") or "http://localhost:5000").rstrip("/")
    static_pages = [
        ("/", 1.0, "daily"),
        ("/cheats", 0.9, "daily"),
        ("/games", 0.8, "daily"),
        ("/status", 0.6, "hourly"),
        ("/faq", 0.5, "monthly"),
        ("/feedback", 0.5, "weekly"),
        ("/loader", 0.5, "monthly"),
        ("/terms-of-service", 0.2, "yearly"),
        ("/privacy", 0.2, "yearly"),
    ]
    urls = []
    for path, priority, freq in static_pages:
        urls.append(
            f"  <url><loc>{site_url}{path}</loc><changefreq>{freq}</changefreq>"
            f"<priority>{priority:.1f}</priority></url>"
        )
    products = Product.query.order_by(Product.created_at.desc()).all()
    for p in products:
        lastmod = (p.updated_at or p.created_at or datetime.utcnow()).strftime("%Y-%m-%d")
        urls.append(
            f"  <url><loc>{site_url}{url_for('main.product_detail', slug=p.slug)}</loc>"
            f"<lastmod>{lastmod}</lastmod><changefreq>daily</changefreq>"
            f"<priority>0.9</priority></url>"
        )
    games = sorted({
        p.game_slug for p in products if p.game_slug
    })
    for slug in games:
        urls.append(
            f"  <url><loc>{site_url}{url_for('main.game_page', game_slug=slug)}</loc>"
            f"<changefreq>daily</changefreq><priority>0.7</priority></url>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>"
    )
    return Response(xml, mimetype="application/xml")


@main_bp.route("/robots.txt")
def robots():
    site_url = (current_app.config.get("SITE_URL") or "http://localhost:5000").rstrip("/")
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /my-keys\n"
        "Disallow: /profile\n"
        "Disallow: /checkout\n"
        f"Sitemap: {site_url}/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@main_bp.route("/plan/<int:tier_id>")
def plan_detail(tier_id):
    tier = db.session.get(PricingTier, tier_id)
    if not tier:
        abort(404)
    product = Product.query.filter_by(id=tier.product_id).first()
    if not product:
        abort(404)
    return redirect(url_for("main.product_detail", slug=product.slug, tier_id=tier_id))


@main_bp.route("/loader")
def loader():
    products = Product.query.order_by(Product.created_at.asc()).all()
    loader_cfg = get_loader_config()
    return render_template(
        "loader.html",
        product=None,
        products=products,
        loader_url=loader_cfg["loader_url"],
        loader_public_url=loader_cfg["loader_public_url"],
        loader_private_url=loader_cfg["loader_private_url"],
    )


@main_bp.route("/loader/<slug>")
def loader_product(slug):
    """Product-specific loader guide (VAL-LOADER-002).

    Additive presentation hook: renders the same loader.html template with
    product context (name, status, loader_url, buyer_notes) so each product
    gets correct download instructions and loader URL. The generic /loader
    route above is unchanged.
    """
    product = Product.query.filter_by(slug=slug).first()
    if not product:
        abort(404)
    products = Product.query.order_by(Product.created_at.asc()).all()
    loader_cfg = get_loader_config()
    return render_template(
        "loader.html",
        product=product,
        products=products,
        loader_url=loader_cfg["loader_url"],
        loader_public_url=loader_cfg["loader_public_url"],
        loader_private_url=loader_cfg["loader_private_url"],
    )


@main_bp.route("/feedback")
def feedback():
    # Approved reviews only (pending/rejected never render publicly), newest
    # first. The rating summary is derived from this same list — no static
    # figures (NO-FABRICATED-REVIEWS).
    reviews = (
        Review.query.filter_by(status="approved")
        .order_by(Review.created_at.desc())
        .all()
    )
    rating_avg = (
        round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else None
    )
    return render_template("feedback.html", reviews=reviews, rating_avg=rating_avg)


@main_bp.route("/terms-of-service")
def terms():
    return render_template("terms.html")


@main_bp.route("/faq")
def faq():
    # DB-derived game list so the FAQ answer for "which games" can never go
    # stale (VAL-CON-001) — the same card view-model the catalogue uses.
    games = catalogue.group_games(_all_cards())
    return render_template("faq.html", games=games)


@main_bp.route("/privacy")
def privacy():
    return render_template("privacy.html")


@main_bp.route("/health/products")
def health_products():
    allowed, deny = _admin_or_deny()
    if not allowed:
        return deny
    from models import Product
    products = Product.query.all()
    rows = []
    for p in products:
        rows.append({
            "id": p.id,
            "name": p.name,
            "slug": p.slug,
            "visibility": p.visibility,
            "key_source": p.key_source,
            "is_private": p.is_private,
            "has_vc": bool(p.venomcheats_slug),
        })
    import os as _os
    return {
        "count": len(rows),
        "products": rows,
        "vercel": _os.environ.get("VERCEL") == "1",
        "db_path": current_app.config.get("SQLALCHEMY_DATABASE_URI", "")[:80],
    }


@main_bp.route("/health/kv")
def health_kv():
    allowed, deny = _admin_or_deny()
    if not allowed:
        return deny
    import os as _os
    keys_found = {}
    for k in sorted(_os.environ.keys()):
        kl = k.lower()
        if "kv" in kl or "redis" in kl or "upstash" in kl:
            keys_found[k] = _os.environ[k][:20] + "..."
    return {
        "kv_available": bool(_os.environ.get("KV_REST_API_URL") or _os.environ.get("KV_URL")),
        "kv_keys_found": keys_found,
        "all_env_prefixes": sorted(set(k.split("_")[0] for k in _os.environ.keys())),
    }


@main_bp.route("/my-keys")
@login_required
def my_keys():
    keys = (
        Key.query
        .filter_by(user_id=current_user.id)
        .order_by(Key.created_at.desc())
        .all()
    )
    pending_orders = (
        Order.query
        .filter_by(user_id=current_user.id, status="awaiting_keys")
        .order_by(Order.created_at.desc())
        .all()
    )
    # Buyer-facing order history (VAL-ACC-004): completed orders only —
    # pending/awaiting orders stay in the pending explainer above it.
    order_history = (
        Order.query
        .filter_by(user_id=current_user.id, status="completed")
        .order_by(Order.created_at.desc())
        .all()
    )
    loader = get_loader_config()
    discord_cfg = get_discord_config()
    has_private = any(k.product and k.product.visibility == "private" and k.is_active for k in keys)
    now = datetime.utcnow()

    # Key states (VAL-ACC-003): revoked (deactivated) is distinct from expired
    # (time ran out) — a revoked key stays revoked even with time remaining.
    def _key_state(key):
        if not key.is_active:
            return "revoked"
        if key.expires_at and key.expires_at <= now:
            return "expired"
        return "active"

    key_states = {k.id: _key_state(k) for k in keys}
    active_count = sum(1 for state in key_states.values() if state == "active")
    # The "Expired" chip carries every non-usable licence (expired + revoked).
    filter_counts = {
        "all": len(keys),
        "active": active_count,
        "expired": len(keys) - active_count,
    }
    return render_template("keys.html", keys=keys, pending_orders=pending_orders,
        order_history=order_history,
        key_states=key_states, filter_counts=filter_counts,
        loader_token=loader["loader_token"],
        loader_url=loader["loader_url"],
        loader_public_url=loader["loader_public_url"],
        loader_private_url=loader["loader_private_url"],
        discord_public_url=discord_cfg["public_url"],
        discord_private_url=discord_cfg["private_url"],
        has_private=has_private,
        now=now)


@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Account profile (VAL-ACC-005).

    Email and password changes on the shared form system, validated
    per-field server-side: failures re-render the form with field-keyed
    inline errors (works without JS), success redirects with a flash.
    Any change — email or password — requires the account's current
    password.
    """
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        email_changed = bool(email) and email != current_user.email
        password_changed = bool(new_password)
        field_errors = {}

        if not email:
            field_errors["email"] = "Email is required."
        elif email_changed:
            if "@" not in email:
                field_errors["email"] = "Please enter a valid email address."
            else:
                existing = User.query.filter_by(email=email).first()
                if existing and existing.id != current_user.id:
                    field_errors["email"] = "Email already in use."

        if password_changed:
            # Unified 8+ rule — same validator as signup and password reset.
            pw_error = password_error(new_password)
            if pw_error:
                field_errors["new_password"] = pw_error
            if new_password != confirm_password:
                field_errors["confirm_password"] = "New passwords do not match."

        if email_changed or password_changed:
            if not current_password:
                field_errors["current_password"] = (
                    "Enter your current password to save changes."
                )
            elif not current_user.check_password(current_password):
                field_errors["current_password"] = "Current password is incorrect."

        if field_errors:
            return render_template(
                "profile.html",
                field_errors=field_errors,
                form_email=email or current_user.email,
            )

        if email_changed:
            current_user.email = email
        if password_changed:
            current_user.set_password(new_password)

        if email_changed or password_changed:
            db.session.commit()
            # Persist the change (notably an admin password change) to the KV
            # backup immediately — restore_users_to_db() re-applies the backup's
            # password_hash for admins on every boot, so without this the change
            # would be reverted until the 120s periodic backup runs (or forever
            # if the app restarts first). Same pattern as routes/auth.py signup.
            try:
                from utils.kv_store import backup_everything
                backup_everything()
            except Exception:
                pass
        flash("Profile updated.", "success")
        return redirect(url_for("main.profile"))

    return render_template(
        "profile.html", field_errors={}, form_email=current_user.email
    )
