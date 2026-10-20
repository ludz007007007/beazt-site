"""Catalogue surfaces: /, /cheats, /games, /games/<slug>.

Render tests over the Flask test client. Every expectation is computed from
the rows the test inserts, so a hardcoded or fabricated value fails.
"""

import re
from datetime import date, datetime

import pytest

PRODUCT_HREF = re.compile(r'href="/product/([a-z0-9-]+)"')


def _main(html):
    start = html.index("<main")
    return html[start:html.index("</main>", start)]


def _slugs(html):
    return PRODUCT_HREF.findall(_main(html))


def _cards(html):
    """Map slug -> card HTML for every shared product card inside <main>."""
    body = _main(html)
    parts = re.split(r'(?=<article class="product-card)', body)[1:]
    cards = {}
    for part in parts:
        part = part[:part.index("</article>")]
        slug = PRODUCT_HREF.search(part).group(1)
        cards[slug] = part
    return cards


def _text(fragment):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


@pytest.fixture
def catalogue(make_product):
    alpha = make_product(
        "rust-alpha", name="Rust Alpha", game="Rust", status="undetected",
        tiers=[("1 Day", 1, 500, False), ("1 Week", 7, 1800, False)],
    )
    beta = make_product(
        "rust-beta", name="Rust Beta", game="Rust", status="updating",
        tiers=[("1 Month", 30, 3900, False)],
    )
    gamma = make_product(
        "cs2-gamma", name="Gamma Legit", game="Counter-Strike 2", status="detected",
        tiers=[("1 Day", 1, 900, False), ("1 Week", 7, 2500, False), ("1 Month", 30, 5000, False)],
    )
    return {"rust-alpha": alpha, "rust-beta": beta, "cs2-gamma": gamma}


# ---- Product cards --------------------------------------------------------

EXPECTED_LABELS = {"undetected": "Undetected", "updating": "Updating", "detected": "Detected"}


@pytest.mark.parametrize("path", ["/cheats", "/games/rust", "/games/counter-strike-2"])
def test_cards_render_real_db_fields(client, catalogue, path):
    from models import PricingTier

    cards = _cards(client.get(path).get_data(as_text=True))
    assert cards, path
    for slug, card in cards.items():
        product = catalogue[slug]
        tiers = PricingTier.query.filter_by(product_id=product.id).all()
        text = _text(card)
        assert product.name in text
        assert product.display_game in text
        pill = re.search(r'<span class="status-pill status-pill--([a-z]+)">(.*?)</span>\s*</span>|'
                         r'<span class="status-pill status-pill--([a-z]+)">(.*?)</span>', card, re.S)
        assert pill, card
        assert EXPECTED_LABELS[product.status] in _text(pill.group(0))
        assert 'class="status-pill-dot"' in pill.group(0)
        min_price = min(t.price_pence for t in tiers) / 100
        assert f"From £{min_price:.2f}" in text
        if len(tiers) > 1:
            assert f"{len(tiers)} plans" in text


def test_sold_out_badge_follows_pool_stock(client, db, catalogue):
    from models import Key

    db.session.add(Key(product_id=catalogue["rust-alpha"].id, key_value="pool-a-1", is_active=False))
    db.session.commit()
    cards = _cards(client.get("/cheats").get_data(as_text=True))
    assert "Sold out" not in _text(cards["rust-alpha"])
    assert "Sold out" in _text(cards["rust-beta"])


def test_status_labels_use_fixed_taxonomy(client, make_product):
    make_product("p-online", status="online")
    make_product("p-maint", status="maintenance")
    html = client.get("/cheats").get_data(as_text=True)
    labels = re.findall(r'class="status-pill-label">([^<]+)<', _main(html))
    assert labels and set(labels) <= {"Undetected", "Updating", "Detected", "Down", "Risky"}
    assert "Online" not in labels and "Maintenance" not in labels


# ---- Search / filter / sort ----------------------------------------------

def test_search_narrows_catalogue(client, catalogue):
    html = client.get("/cheats?q=gamma").get_data(as_text=True)
    assert _slugs(html) == ["cs2-gamma"]
    assert "Rust Alpha" not in _main(html)

    html = client.get("/cheats?q=zzzznomatch").get_data(as_text=True)
    assert _slugs(html) == []
    assert 'class="empty-state' in _main(html)

    html = client.get("/cheats?q=").get_data(as_text=True)
    assert sorted(_slugs(html)) == sorted(catalogue)


def test_search_matches_game_name(client, catalogue):
    html = client.get("/cheats?q=counter").get_data(as_text=True)
    assert _slugs(html) == ["cs2-gamma"]


def test_status_filter_server_side(client, catalogue):
    assert _slugs(client.get("/cheats?status=undetected").get_data(as_text=True)) == ["rust-alpha"]
    assert _slugs(client.get("/cheats?status=detected").get_data(as_text=True)) == ["cs2-gamma"]
    assert sorted(_slugs(client.get("/cheats?status=").get_data(as_text=True))) == sorted(catalogue)
    # Legacy values from old links still map onto the taxonomy.
    assert _slugs(client.get("/cheats?status=online").get_data(as_text=True)) == ["rust-alpha"]


def test_game_filter_server_side(client, catalogue):
    assert sorted(_slugs(client.get("/cheats?game=rust").get_data(as_text=True))) == ["rust-alpha", "rust-beta"]


def test_sort_by_price(client, catalogue):
    from models import PricingTier

    def min_price(slug):
        return min(t.price_pence for t in PricingTier.query.filter_by(product_id=catalogue[slug].id))

    expected = sorted(catalogue, key=min_price)
    assert _slugs(client.get("/cheats?sort=price_asc").get_data(as_text=True)) == expected
    assert _slugs(client.get("/cheats?sort=price_desc").get_data(as_text=True)) == expected[::-1]
    assert expected != expected[::-1]


def test_invalid_sort_falls_back(client, catalogue):
    default = _slugs(client.get("/cheats").get_data(as_text=True))
    resp = client.get("/cheats?sort=%27%3Bdrop&status=nonsense&q=%3Cscript%3E")
    assert resp.status_code == 200
    assert _slugs(client.get("/cheats?sort=bogus").get_data(as_text=True)) == default


def test_cheats_has_filter_toolbar(client, catalogue):
    main = _main(client.get("/cheats").get_data(as_text=True))
    for name in ("q", "status", "sort", "game"):
        assert re.search(rf'name="{name}"', main), name
    assert re.search(r'<form[^>]*method="get"', main)


# ---- Auto-submit filters (VAL-ST-002) ------------------------------------

def test_filter_bar_declares_autosubmit(client, catalogue):
    main = _main(client.get("/cheats").get_data(as_text=True))
    form = re.search(r"<form\b.*?</form>", main, re.S).group(0)
    assert "data-autosubmit" in form
    # No inline handlers: the wiring lives in script.js.
    assert not re.search(r"\son[a-z]+=", form)
    # Apply survives in markup as the no-JS fallback (hidden once JS wires up).
    assert 'class="btn btn-secondary filter-bar__apply"' in form


def test_script_js_wires_autosubmit():
    import os

    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static/js/script.js"),
        encoding="utf-8",
    ).read()
    assert 'querySelector("form[data-autosubmit]")' in src
    assert "filter-bar--auto" in src  # CSS hook that hides the Apply fallback
    assert "change" in src and "setTimeout" in src  # selects immediate, search debounced


def test_count_line_reflects_filters_not_sort(client, catalogue):
    unfiltered = _text(_main(client.get("/cheats").get_data(as_text=True)))
    assert "3 products" in unfiltered
    assert "Showing" not in unfiltered
    filtered = _text(_main(client.get("/cheats?game=rust").get_data(as_text=True)))
    assert "Showing 2 of 3 products" in filtered
    sorted_only = _text(_main(client.get("/cheats?sort=price_asc").get_data(as_text=True)))
    assert "Showing" not in sorted_only
    assert "sorted by price: low to high" in sorted_only


def test_empty_filter_state_offers_reset(client, catalogue):
    main = _main(client.get("/cheats?q=zzzznomatch").get_data(as_text=True))
    assert "No products match these filters" in _text(main)
    assert re.search(r'<a href="/cheats"[^>]*>Clear filters</a>', main)


# ---- Game landing art treatment ------------------------------------------

def test_game_landing_hero_uses_real_statuses(client, catalogue):
    main = _main(client.get("/games/rust").get_data(as_text=True))
    assert re.search(r'class="game-hero game-hero--m[0-3]"', main)
    assert 'id="game-hero-title">Rust</h1>' in main
    # One left-edge segment per product, coloured by its real status.
    segs = re.findall(r"game-hero__edge-seg--([a-z]+)", main)
    assert sorted(segs) == ["undetected", "updating"]
    # The shared ratio strip summarises the same DB data.
    assert 'aria-label="Status of 2 products: 1 undetected, 1 updating"' in main
    text = _text(main)
    assert "1 of 2" in text  # honest undetected ratio
    assert "£5.00" in text  # from-price across the game's tiers
    assert "3 plans" in text  # plan count across the game's tiers


def test_games_index_cards_show_ratio_and_plans(client, catalogue):
    from models import PricingTier, Product

    products = Product.query.all()
    by_game = {}
    for p in products:
        by_game.setdefault(p.game_slug, []).append(p)
    main = _main(client.get("/games").get_data(as_text=True))
    tiles = re.findall(r'<article class="game-card".*?</article>', main, re.S)
    assert len(tiles) == len(by_game)
    for tile in tiles:
        slug = re.search(r'href="/games/([a-z0-9-]+)"', tile).group(1)
        game_products = by_game[slug]
        assert tile.count("ratio-strip__seg--") == len(game_products)
        n = sum(PricingTier.query.filter_by(product_id=p.id).count() for p in game_products)
        assert f"{n} plan{'' if n == 1 else 's'}" in _text(tile)


def test_group_games_art_data_is_deterministic(client, catalogue):
    import zlib

    from utils import catalogue as vm

    cards = vm.build_cards(list(catalogue.values()))
    games = {g["slug"]: g for g in vm.group_games(cards)}
    rust = games["rust"]
    assert rust["motif"] == zlib.crc32(b"rust") % 4
    assert rust["tier_count"] == 3  # 2 (alpha) + 1 (beta)
    assert rust["status_counts"] == [("undetected", "Undetected", 1), ("updating", "Updating", 1)]
    assert [s for s, _ in rust["segments"]] == ["undetected", "updating"]  # safest first


# ---- Honest freshness -----------------------------------------------------

def _today_variants():
    today = date.today()
    return {
        today.strftime("%A, %B %d, %Y"),
        today.strftime("%d %b %Y"),
        f"{today.day} {today.strftime('%b %Y')}",
        today.strftime("%Y-%m-%d"),
    }


def test_verified_dates_come_from_db(client, db, catalogue):
    alpha = catalogue["rust-alpha"]
    alpha.last_verified_at = datetime(2024, 1, 15, 12, 0)
    db.session.commit()
    for path in ("/cheats", "/", "/status"):
        html = client.get(path).get_data(as_text=True)
        main = _main(html)
        assert "15 Jan 2024" in main, path
        for variant in _today_variants():
            assert variant not in main, (path, variant)
    cards = _cards(client.get("/cheats").get_data(as_text=True))
    assert "Last verified 15 Jan 2024" in _text(cards["rust-alpha"])
    assert "Not yet verified" in _text(cards["rust-beta"])
    assert "15 Jan 2024" not in cards["rust-beta"]


def test_status_event_date_used_when_not_verified(client, db, catalogue):
    from models import StatusEvent

    db.session.add(StatusEvent(product_id=catalogue["rust-beta"].id, status="updating",
                               created_at=datetime(2025, 3, 2, 9, 0)))
    db.session.commit()
    cards = _cards(client.get("/cheats").get_data(as_text=True))
    assert "Updating since 2 Mar 2025" in _text(cards["rust-beta"])


# ---- Homepage -------------------------------------------------------------

def _hero(html):
    m = re.search(r'<section class="home-hero.*?</section>', html, re.S)
    assert m, "hero section missing"
    return m.group(0)


def test_homepage_hero_value_prop_and_cta(client, catalogue):
    html = client.get("/").get_data(as_text=True)
    hero = _hero(html)
    h1 = _text(re.search(r"<h1.*?</h1>", hero, re.S).group(0))
    assert h1 != "BEAZT"
    assert re.search(r"cheat|private", h1, re.I)
    assert re.search(r"player|rust|cs2|counter-strike|apex", h1, re.I)
    primaries = re.findall(r'<a href="([^"]+)" class="btn btn-primary[^"]*">(.*?)</a>', hero, re.S)
    assert len(primaries) == 1
    href, label = primaries[0]
    assert re.match(r"^(Get access|Browse|View|Start|Buy)", _text(label))
    assert client.get(href).status_code == 200
    assert "Learn more" not in hero and 'href="#"' not in hero
    assert re.search(r"status|delivered|My Keys", _text(hero), re.I)


BANNED = ["2,400", "2400+", "4.9", "99.9", "&lt;15s", "<15s", "&lt;2m", "<2m",
          "Avg Buyer Rating", "Uptime", "Systems Online", "100% undetected"]


def test_homepage_has_no_fabricated_stats(client, catalogue):
    html = client.get("/").get_data(as_text=True)
    for phrase in BANNED:
        assert phrase not in html, phrase
    assert "data-stat=" not in html
    assert "data-footer-stat=" not in html


def test_honest_stats_reflect_db(client, db, catalogue, make_user):
    from models import Order, PricingTier, Review

    buyer = make_user("statbuyer")
    tier = PricingTier.query.filter_by(product_id=catalogue["rust-alpha"].id).first()
    for i in range(3):
        db.session.add(Order(user_id=buyer.id, tier_id=tier.id, status="completed",
                             stripe_session_id=f"stat-{i}"))
    db.session.add(Order(user_id=buyer.id, tier_id=tier.id, status="pending", stripe_session_id="stat-p"))
    db.session.add(Review(user_id=buyer.id, product_id=catalogue["rust-alpha"].id, rating=5,
                          body="Works as described.", status="approved"))
    db.session.add(Review(user_id=buyer.id, product_id=catalogue["cs2-gamma"].id, rating=4,
                          body="Decent, some setup.", status="approved"))
    db.session.add(Review(user_id=buyer.id, product_id=catalogue["rust-beta"].id, rating=1,
                          body="Pending review body.", status="pending"))
    db.session.commit()
    html = client.get("/").get_data(as_text=True)
    stats = dict(re.findall(r'data-stat="([a-z_]+)"[^>]*>\s*<span class="stat-strip__value[^"]*">([^<]+)<', html))
    assert stats.get("orders_delivered") == "3"
    assert stats.get("rating_avg") == "4.5"
    assert stats.get("review_count") == "2"
    footer = html[html.index('<footer class="site-footer'):]
    assert re.search(r'data-footer-stat="orders_delivered">3 orders delivered', footer)


def test_homepage_and_cheats_are_distinct(client, catalogue, make_product):
    make_product("apex-delta", name="Apex Delta", game="Apex Legends")
    total = 4
    home = _main(client.get("/").get_data(as_text=True))
    cheats = _main(client.get("/cheats").get_data(as_text=True))
    for name in ("q", "status", "sort"):
        assert f'name="{name}"' not in home
        assert f'name="{name}"' in cheats
    assert 0 < len(PRODUCT_HREF.findall(home)) < total
    assert len(PRODUCT_HREF.findall(cheats)) == total
    assert 'href="/cheats"' in home
    headings = lambda h: re.findall(r"<h[12][^>]*>(.*?)</h[12]>", h, re.S)
    assert headings(home) != headings(cheats)


def test_homepage_shows_bounded_subset_with_three_products(client, catalogue):
    home = _main(client.get("/").get_data(as_text=True))
    assert 0 < len(PRODUCT_HREF.findall(home)) < 3


def test_homepage_hero_price_anchor_is_db_derived(client, catalogue):
    """The hero from-price is the true minimum tier price across the games."""
    home = _main(client.get("/").get_data(as_text=True))
    m = re.search(r'class="home-hero__price"[^>]*>\s*Plans from <strong>([^<]+)</strong>', home)
    assert m, "hero from-price line missing"
    # Cheapest tier in the catalogue fixture is rust-alpha "1 Day" at 500p.
    assert m.group(1) == "£5.00"


def test_homepage_delivery_promise_is_canonical(client, catalogue):
    """Home uses the one canonical delivery promise; retired variants absent."""
    html = client.get("/").get_data(as_text=True)
    assert "Your key appears in your account the moment payment is confirmed" in html
    assert "usually within seconds" in html
    for banned in ("within minutes", "15 seconds"):
        assert banned not in html


def test_homepage_sections_carry_index_numbers(client, catalogue):
    """SIGNAL section index (01..05) decorates homepage section eyebrows."""
    html = client.get("/").get_data(as_text=True)
    indexes = re.findall(r'<span class="section-index" aria-hidden="true">(\d+)</span>', html)
    assert indexes == ["01", "02", "03", "04", "05"]


def test_homepage_reviews_render_shared_partial(client, db, catalogue, make_user):
    """Verified reviews come through partials/review_card.html (the one card)."""
    from models import Review

    buyer = make_user("homebuyer")
    db.session.add(Review(user_id=buyer.id, product_id=catalogue["rust-alpha"].id, rating=5,
                          title="Solid", body="Does what it says.", status="approved"))
    db.session.commit()
    home = _main(client.get("/").get_data(as_text=True))
    assert 'class="review-card"' in home
    assert 'class="reviews-grid"' in home
    assert "Verified buyer" in home



# ---- No duplicates --------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/cheats", "/games/rust"])
def test_no_product_rendered_twice(client, catalogue, make_product, path):
    make_product("rust-private", name="Rust Private", game="Rust", visibility="private", is_private=True)
    slugs = _slugs(client.get(path).get_data(as_text=True))
    assert slugs
    assert len(slugs) == len(set(slugs)), slugs


# ---- Games ----------------------------------------------------------------

def test_game_pages_list_exactly_that_game(client, catalogue):
    from models import Product

    groups = {}
    for p in Product.query.all():
        groups.setdefault(p.game_slug, set()).add(p.slug)
    for game_slug, expected in groups.items():
        html = client.get(f"/games/{game_slug}").get_data(as_text=True)
        assert sorted(_slugs(html)) == sorted(expected)
        assert re.search(r'<nav class="breadcrumb" aria-label="Breadcrumb">', html)


def test_games_index_counts_match_db(client, catalogue):
    from models import Product

    counts = {}
    for p in Product.query.all():
        counts[p.game_slug] = counts.get(p.game_slug, 0) + 1
    main = _main(client.get("/games").get_data(as_text=True))
    tiles = re.findall(r'<article class="game-card".*?</article>', main, re.S)
    assert len(tiles) == len(counts)
    for tile in tiles:
        slug = re.search(r'href="/games/([a-z0-9-]+)"', tile).group(1)
        n = counts[slug]
        assert f"{n} product{'' if n == 1 else 's'}" in _text(tile)
        assert client.get(f"/games/{slug}").status_code == 200


def test_unknown_game_404(client, catalogue):
    assert client.get("/games/not-a-game").status_code == 404


def test_empty_catalogue_states(client, db):
    assert 'class="empty-state' in _main(client.get("/cheats").get_data(as_text=True))
    assert 'class="empty-state' in _main(client.get("/games").get_data(as_text=True))
    assert client.get("/").status_code == 200


# ---- One card implementation ---------------------------------------------

def test_product_card_markup_only_in_partial():
    import os

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
    offenders = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace("\\", "/")
            src = open(path, encoding="utf-8").read()
            if rel != "partials/product_card.html" and 'class="product-card' in src:
                offenders.append(rel)
            if "cheat-card" in src:
                offenders.append(rel + " (cheat-card)")
    assert offenders == []
