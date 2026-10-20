"""The /status board (VAL-ST-007, VAL-ST-004, VAL-CROSS-004).

A responsive 4-column board on the design system: aligned grid ≥900px,
stacked labelled cards below it with Product/Game/Updated/Status all
rendered; the unified status-pill taxonomy plus a separate availability
badge; real DB dates; the ChairFBI bases section; and the reduced-motion
safe data-refresh sweep.
"""

import re
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE_CSS = (ROOT / "static" / "css" / "src" / "site.css").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "js" / "script.js").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "status.html").read_text(encoding="utf-8")


def _main(html):
    start = html.index("<main")
    return html[start:html.index("</main>", start)]


def _board(html):
    m = re.search(r'<div class="status-board[^"]*" role="table"[^>]*data-status-board.*?(?=<div class="status-bases|<div class="status-note|</section>)', _main(html), re.S)
    assert m, "product status board missing"
    return m.group(0)


def _rows(html):
    """slug -> row markup for every product row on the board."""
    rows = {}
    for m in re.finditer(r'<div class="status-row" role="row" data-status-row="([^"]+)" data-status="([^"]+)">(.*?)</div>\s*(?=<div class="status-row|</div>)', _board(html), re.S):
        rows[m.group(1)] = {"status": m.group(2), "html": m.group(0)}
    return rows


@pytest.fixture
def catalogue(make_product):
    return {
        "rust-alpha": make_product(
            "rust-alpha", name="Rust Alpha", game="Rust", status="undetected",
            tiers=[("1 Day", 1, 500, False), ("1 Week", 7, 1800, False)],
        ),
        "rust-beta": make_product(
            "rust-beta", name="Rust Beta", game="Rust", status="updating",
            tiers=[("1 Month", 30, 3900, False)],
        ),
        "cs2-gamma": make_product(
            "cs2-gamma", name="Gamma Legit", game="Counter-Strike 2", status="detected",
            tiers=[("1 Day", 1, 900, False)],
        ),
    }


# ---- Board structure (VAL-ST-007) -----------------------------------------

def test_board_header_labels_and_aria_roles(client, catalogue):
    html = client.get("/status").get_data(as_text=True)
    board = _board(html)
    for label in ("Product", "Game", "Updated", "Status"):
        assert re.search(r'role="columnheader">%s<' % label, board), label
    assert board.count('role="row"') == 4  # header + 3 products
    assert board.count('role="cell"') == 12  # four fields per product
    assert 'aria-label="Product status board"' in board


def test_board_rows_carry_all_four_fields(client, catalogue):
    rows = _rows(client.get("/status").get_data(as_text=True))
    assert set(rows) == {"rust-alpha", "rust-beta", "cs2-gamma"}
    for slug, row in rows.items():
        html = row["html"]
        assert 'href="/product/%s"' % slug in html, slug
        assert re.search(r'status-cell--game[^>]*>.*?<a class="status-game-link" href="/games/', html, re.S), slug
        assert "data-status-fresh" in html, slug
        assert "status-pill--" in html, slug
        # Every field keeps an explicit label so stacked cards stay readable.
        for field in ("Product", "Game", "Updated", "Status"):
            assert '">%s</span>' % field in html, (slug, field)


def test_board_css_never_hides_field_values():
    """Under 900px the board stacks instead of dropping columns (VAL-ST-007).

    Scans the Page: Status CSS (bounded at the next page section so later
    sections with their own display rules don't trip the guard): display:none
    may only hide the redundant per-cell labels (desktop, where column
    headers carry them) and the header row when stacked — never a field value.
    """
    section = SITE_CSS[SITE_CSS.index("/* ---- Page: Status"):]
    section = re.split(r"/\* ---- Page: (?!Status)", section)[0]
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", section):
        selector, body = m.group(1), m.group(2)
        if "display: none" not in body and "display:none" not in body:
            continue
        allowed = any(tok in selector for tok in (".status-field-label", ".status-row--head"))
        assert allowed, "display:none on board selector: %s" % selector.strip()
    # The <900px block stacks rows into single-column cards and shows labels.
    mobile = re.search(r"@media \(max-width: 899px\)\s*\{", section)
    assert mobile, "stacking breakpoint missing"
    tail = section[mobile.start():]
    assert re.search(r"\.status-row\s*\{[^}]*grid-template-columns:\s*minmax\(0, ?1fr\)", tail)
    assert re.search(r"\.status-field-label\s*\{[^}]*display: block", tail)


# ---- Taxonomy + availability (VAL-ST-004 / VAL-CROSS-004) ------------------

def test_board_pills_match_catalogue_and_product_page(client, catalogue):
    """Same product, same pill markup + label on catalogue and board."""
    cheats = _main(client.get("/cheats").get_data(as_text=True))
    rows = _rows(client.get("/status").get_data(as_text=True))
    board_html = _board(client.get("/status").get_data(as_text=True))
    for slug, row in rows.items():
        card = re.split(r'(?=<article class="product-card)', cheats)
        card = next((c for c in card if 'href="/product/%s"' % slug in c), None)
        assert card, slug
        pill_re = r'<span class="status-pill status-pill--[a-z]+"><span class="status-pill-dot" aria-hidden="true"></span><span class="status-pill-label">[^<]+</span></span>'
        board_pill = re.search(pill_re, row["html"]).group(0)
        card_pill = re.search(pill_re, card).group(0)
        assert board_pill == card_pill, slug
        assert row["status"] in board_pill
    # Raw provider strings never leak onto the board.
    for banned in ("UNDETECTED", "Online", "Maintenance", "In Stock"):
        assert banned not in board_html, banned


def test_board_availability_badges_follow_stock(client, db, catalogue):
    from models import Key

    # rust-alpha: pool with one spare key -> In stock.
    db.session.add(Key(product_id=catalogue["rust-alpha"].id, key_value="k1", is_active=False))
    db.session.commit()
    rows = _rows(client.get("/status").get_data(as_text=True))
    assert "In stock" in rows["rust-alpha"]["html"]
    assert "badge-availability--in_stock" in rows["rust-alpha"]["html"]
    # rust-beta: pool, no spare keys -> Sold out. cs2-gamma has a plan -> Sold out.
    assert "Sold out" in rows["rust-beta"]["html"]
    assert "Sold out" in rows["cs2-gamma"]["html"]


def test_availability_precedence_private_wins(client, db, make_product):
    make_product("hidden-one", game="Rust", visibility="private")
    rows = _rows(client.get("/status").get_data(as_text=True))
    assert "Private build" in rows["hidden-one"]["html"]
    assert "Sold out" not in rows["hidden-one"]["html"]


# ---- Honest dates -----------------------------------------------------------

def test_board_dates_come_from_db_not_render_time(client, db, catalogue):
    alpha = catalogue["rust-alpha"]
    alpha.last_verified_at = datetime(2024, 1, 15, 12, 0)
    db.session.commit()
    row = _rows(client.get("/status").get_data(as_text=True))["rust-alpha"]["html"]
    assert re.search(r'data-status-fresh[^>]*>.*?<time datetime="2024-01-15">Last verified 15 Jan 2024</time>', row, re.S)
    today = date.today()
    for variant in (today.strftime("%d %b %Y"), f"{today.day} {today.strftime('%b %Y')}"):
        assert variant not in row


# ---- Bases section ----------------------------------------------------------

def test_bases_section_renders_from_provider_data(client, catalogue, monkeypatch):
    import routes.main as main

    fake = [
        {"id": 1, "name": "Base Alpha", "enabled": True, "status": "up"},
        {"id": 2, "name": "Base Beta", "enabled": True, "status": None},
        {"id": 3, "name": "Base Gamma", "enabled": False, "status": None},
    ]
    monkeypatch.setattr(main, "_fetch_chairfbi_bases", lambda: fake)
    html = client.get("/status").get_data(as_text=True)
    assert "Loader base status" in html
    assert "Base Alpha" in html and "Base Beta" in html and "Base Gamma" in html
    assert '<span class="pill pill-dot pill-success">Operational</span>' in html
    assert '<span class="pill pill-dot pill-warn">Degraded</span>' in html
    assert '<span class="pill pill-dot pill-danger">Offline</span>' in html


def test_bases_section_omits_cleanly_when_unconfigured(client, catalogue, monkeypatch):
    import routes.main as main

    monkeypatch.setattr(main, "_fetch_chairfbi_bases", lambda: None)
    html = client.get("/status").get_data(as_text=True)
    assert "Loader base status" not in html
    assert "status-bases" not in html


# ---- Markup hygiene + sweep -------------------------------------------------

def test_status_template_has_no_inline_styles():
    assert "style=" not in TEMPLATE


def test_sweep_signature_css_and_js_reduced_motion_safe():
    # CSS: one-shot sheen on .is-swept, explicitly disabled under reduce.
    assert ".status-row.is-swept::after" in SITE_CSS
    assert re.search(r"@keyframes status-sweep", SITE_CSS)
    assert re.search(
        r"@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.status-row\.is-swept::after\s*\{[^}]*animation:\s*none",
        SITE_CSS,
    )
    # JS: refresh diff loop + sweep gated behind the reduced-motion check.
    setup = SCRIPT[SCRIPT.index("function setupStatusBoard"):SCRIPT.index("function hydrateIcons")]
    assert "[data-status-board]" in setup
    assert "data-status-fresh" in setup and "data-status-pill" in setup
    assert "function sweepRow" in setup
    assert re.search(r"function sweepRow\(row\) \{\s*if \(reducedMotion\) \{ return; \}", setup)
    assert "window.BEAZT.statusRefresh" in setup
