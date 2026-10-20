"""Typographic cover generator (utils/covers.py) + OG image wiring.

Covers the art-direction contract (VAL-ST-008): every product and game
renders a distinct, deterministic visual; covers carry intrinsic
dimensions and lazy loading; the default og:image is present on all pages.
"""

import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OG_DEFAULT = "images/og-default.png"


def _png_size(data):
    """PNG IHDR: width/height are big-endian uint32 at bytes 16..24."""
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _meta(html, prop):
    for line in html.splitlines():
        s = line.strip()
        if prop in s and ("property=" in s or "name=" in s):
            return s
    return ""


# --- /cheat-image/<slug> ------------------------------------------------------

def test_cover_is_deterministic(client, make_product):
    make_product(slug="cover-det", name="Cover Det", game="Coverdet")
    a = client.get("/cheat-image/cover-det")
    b = client.get("/cheat-image/cover-det")
    assert a.status_code == 200 and b.status_code == 200
    assert a.mimetype == "image/png"
    assert a.data == b.data, "same product must render identical bytes"


def test_covers_differ_between_games(client, make_product):
    make_product(slug="game-a", name="Game A Tool", game="Alpha")
    make_product(slug="game-b", name="Game B Tool", game="Beta")
    make_product(slug="game-c", name="Game C Tool", game="Gamma")
    bodies = [client.get(f"/cheat-image/{s}").data for s in ("game-a", "game-b", "game-c")]
    assert len({body for body in bodies}) == 3, "different games never share a cover"


def test_covers_differ_between_products_of_same_game(client, make_product):
    make_product(slug="same-game-1", name="First Tool", game="Shared")
    make_product(slug="same-game-2", name="Second Tool", game="Shared")
    a = client.get("/cheat-image/same-game-1").data
    b = client.get("/cheat-image/same-game-2").data
    assert a != b


def test_cover_variants_differ(client, make_product):
    make_product(slug="variant-prod", name="Variant Prod", game="Variant")
    seen = {client.get(f"/cheat-image/variant-prod?v={v}").data for v in range(4)}
    assert len(seen) == 4, "gallery variants must be distinct shots"


def test_cover_has_intrinsic_16_9_dimensions(client, make_product):
    make_product(slug="dim-prod", name="Dim Prod", game="Dim")
    resp = client.get("/cheat-image/dim-prod")
    assert resp.status_code == 200
    assert _png_size(resp.data) == (1200, 675)


def test_unknown_slug_404s(client):
    assert client.get("/cheat-image/does-not-exist").status_code == 404
    assert client.get("/game-image/does-not-exist").status_code == 404


def test_game_covers_distinct_per_game(client, make_product):
    make_product(slug="ga-1", name="GA One", game="Ga Game")
    make_product(slug="gb-1", name="GB One", game="Gb Game")
    a = client.get("/game-image/ga-game")
    b = client.get("/game-image/gb-game")
    assert a.status_code == 200 and b.status_code == 200
    assert a.mimetype == "image/png"
    assert a.data != b.data


def test_game_cover_dominant_status_color(client, make_product):
    # Detected dominates (2 of 3) -> the accent bar must be the detected red,
    # not the undetected green of the majority-safe tie policy.
    from utils.covers import STATUS_COLORS

    for slug in ("ds-1", "ds-2", "ds-3"):
        make_product(slug=slug, name=slug.upper(), game="Dominant", status="undetected")
    from models import Product

    rows = Product.query.filter(Product.slug.in_(["ds-1", "ds-2", "ds-3"])).all()
    rows[0].status = "detected"
    rows[1].status = "detected"
    from models import db

    db.session.commit()
    data = client.get("/game-image/dominant").data
    # Sample the left-edge accent bar pixel (PNG decode via Pillow).
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    assert img.getpixel((4, 300)) == STATUS_COLORS["detected"]


# --- OG images ----------------------------------------------------------------

def test_default_og_image_on_all_pages(client):
    for path in ("/", "/cheats", "/games", "/status", "/faq", "/auth/login"):
        html = client.get(path).get_data(as_text=True)
        assert 'property="og:image"' in html, path
        assert OG_DEFAULT in html, path
        assert 'name="twitter:image"' in html, path


def test_og_default_file_exists_and_is_png():
    path = os.path.join(ROOT, "static", OG_DEFAULT)
    with open(path, "rb") as fh:
        data = fh.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert _png_size(data) == (1200, 675)


def test_product_page_og_image_is_cover(client, make_product):
    make_product(slug="og-prod", name="OG Prod", game="OG Game")
    html = client.get("/product/og-prod").get_data(as_text=True)
    og = _meta(html, "og:image")
    assert "/cheat-image/og-prod" in og, og
    assert og.count("http") >= 1, "og:image must be absolute"
    # Exactly one og:image tag (base default overridden, not duplicated).
    assert html.count('property="og:image"') == 1


def test_product_page_og_image_prefers_gallery(client, make_product):
    make_product(slug="og-gal", name="OG Gal", game="OG Game",
                 gallery_images='["/static/images/hero.webp"]')
    html = client.get("/product/og-gal").get_data(as_text=True)
    og = _meta(html, "og:image")
    assert "/static/images/hero.webp" in og, og
    assert og.startswith('<meta property="og:image" content="http')


def test_no_duplicate_og_tags_on_product_page(client, make_product):
    make_product(slug="og-dup", name="OG Dup", game="OG Game")
    html = client.get("/product/og-dup").get_data(as_text=True)
    for prop in ('property="og:title"', 'property="og:description"',
                 'property="og:type"', 'property="og:url"',
                 'name="twitter:image"', 'name="twitter:card"'):
        assert html.count(prop) == 1, prop


def test_game_page_og_image_is_game_cover(client, make_product):
    make_product(slug="gog-1", name="GOG One", game="Gog Game")
    html = client.get("/games/gog-game").get_data(as_text=True)
    og = _meta(html, "og:image")
    assert "/game-image/gog-game" in og, og


# --- Markup contract ----------------------------------------------------------

def test_card_covers_lazy_with_intrinsic_dims(client, make_product):
    make_product(slug="lazy-prod", name="Lazy Prod", game="Lazy Game")
    html = client.get("/cheats").get_data(as_text=True)
    segment = html[html.index("product-card__media"):]
    card_img = segment[segment.index("<img"):]
    card_img = card_img[: card_img.index(">") + 1]
    assert 'loading="lazy"' in card_img
    assert 'width="1200"' in card_img and 'height="675"' in card_img
    assert "onerror=" not in card_img, "no inline on*= handlers"


def test_game_tiles_render_covers(client, make_product):
    make_product(slug="tile-prod", name="Tile Prod", game="Tile Game")
    html = client.get("/games").get_data(as_text=True)
    assert "/game-image/tile-game" in html


def test_no_shared_placeholder_reference(client, db):
    """The old shared Rust placeholder must be gone from demo data and markup."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "seed_demo", os.path.join(ROOT, "scripts", "seed_demo.py")
    )
    seed_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_module)
    seed_module.seed_demo_data()
    from models import Product

    for p in Product.query.all():
        assert p.image_url != "/static/icons/rust_placeholder.jpg", p.slug
    html = client.get("/cheats").get_data(as_text=True)
    assert "rust_placeholder" not in html
