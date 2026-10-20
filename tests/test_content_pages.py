"""Content pages (m3-content-pages): FAQ, loader guide, legal pages, 404.

Covers VAL-CON-001..004 and the VAL-CROSS-005 recovery path:

- VAL-CON-001  FAQ reflects the real catalogue and quotes the ONE canonical
               delivery promise (single source: partials/copy.html).
- VAL-CON-002  /loader and /loader/<slug> render with intentional
               unconfigured download states (no dead links).
- VAL-CON-003  Terms and privacy render on the design system.
- VAL-CON-004  The 404 is a branded recovery page linking catalogue, status
               and home, with no inline stylesheet.
- VAL-CROSS-005  Unknown URLs render the branded 404 (no stack trace).
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL_DIR = os.path.join(ROOT, "templates")
CSS_DIR = os.path.join(ROOT, "static", "css")

CANONICAL_PROMISE = (
    "Your key appears in your account the moment payment is confirmed"
    " — usually within seconds."
)
RETIRED_CLAIMS = (
    "under 15 seconds",
    "usually within minutes",
    "within minutes after payment",
    "hit your dashboard",
    "targets Rust",
)


def _all_templates():
    """(relative path, source) for every template in the tree."""
    for dirpath, _dirs, files in os.walk(TPL_DIR):
        for name in files:
            if name.endswith(".html"):
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, TPL_DIR).replace("\\", "/")
                yield rel, open(path, encoding="utf-8").read()


def _main(html):
    start = html.index("<main")
    return html[start:html.index("</main>", start)]


# ---- VAL-CON-001: one canonical delivery promise ---------------------------

def test_delivery_promise_is_defined_exactly_once():
    """The promise lives in partials/copy.html and nowhere else verbatim."""
    hits = [rel for rel, src in _all_templates() if CANONICAL_PROMISE in src]
    assert hits == ["partials/copy.html"], hits


def test_retired_delivery_claims_absent_from_all_templates():
    for rel, src in _all_templates():
        for banned in RETIRED_CLAIMS:
            assert banned not in src, f"{rel}: {banned!r}"


def test_delivery_promise_renders_identically_on_all_key_surfaces(
    client, catalogue, buyer_client
):
    """FAQ, loader, keys, home and feedback render the same sentence."""
    paths = ["/", "/faq", "/loader", "/feedback"]
    for path in paths:
        html = client.get(path).get_data(as_text=True)
        assert CANONICAL_PROMISE in html, f"{path} missing the canonical promise"
    assert CANONICAL_PROMISE in buyer_client.get("/my-keys").get_data(as_text=True)
    assert CANONICAL_PROMISE in client.get("/product/rust-alpha").get_data(as_text=True)


def test_loader_info_callout_uses_canonical_promise(client, catalogue):
    html = client.get("/loader").get_data(as_text=True)
    assert CANONICAL_PROMISE in html


# ---- VAL-CON-001: FAQ reflects the real catalogue --------------------------

def test_faq_lists_every_game_in_the_catalogue(client, catalogue):
    html = _main(client.get("/faq").get_data(as_text=True))
    for game in ("Rust", "Counter-Strike 2"):
        assert game in html, game
    assert "targets Rust" not in html


def test_faq_answers_top_buyer_questions(client, catalogue):
    html = _main(client.get("/faq").get_data(as_text=True))
    # Delivery, status meaning, requirements, support.
    assert CANONICAL_PROMISE in html
    assert "My Keys" in html
    for label in ("Undetected", "Updating", "Risky", "Detected"):
        assert label in html, label
    assert "Windows 10" in html
    assert "Discord" in html


def test_faq_deep_link_ids_are_stable(client, catalogue):
    """faq-answer-1..10 are referenced by the homepage and must never be
    renumbered; 11 (status meaning) and 12 (requirements) are new."""
    src = open(os.path.join(TPL_DIR, "faq.html"), encoding="utf-8").read()
    ids = {int(n) for n in re.findall(r'id="faq-answer-(\d+)"', src)}
    assert ids == set(range(1, 13))


def test_faq_search_count_matches_answer_count(client, catalogue):
    src = open(os.path.join(TPL_DIR, "faq.html"), encoding="utf-8").read()
    assert src.count('class="faq-item"') == 12
    assert ">12 answers<" in src


# ---- VAL-CON-002: loader guide --------------------------------------------

def test_loader_pages_render_with_intentional_unconfigured_state(client, catalogue):
    """No loader URL configured locally: the guide routes to My Keys and
    never renders an empty href (no dead download link)."""
    for path in ("/loader", "/loader/rust-alpha"):
        resp = client.get(path)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'href=""' not in html
        assert "My Keys" in html
        assert CANONICAL_PROMISE in html


def test_loader_guide_is_game_aware(client, catalogue):
    product_html = client.get("/loader/rust-alpha").get_data(as_text=True)
    assert "Launch Rust and verify the overlay" in product_html
    generic_html = client.get("/loader").get_data(as_text=True)
    assert "Launch your game and verify the overlay" in generic_html
    assert "Launch Rust" not in generic_html
    assert "A stable Rust install" not in generic_html


def test_loader_product_guide_lists_all_products(client, catalogue):
    html = _main(client.get("/loader/cs2-gamma").get_data(as_text=True))
    assert 'aria-current="page"' in html


# ---- VAL-CON-003: legal pages ---------------------------------------------

@pytest.mark.parametrize("path", ["/terms-of-service", "/privacy"])
def test_legal_pages_render_on_the_design_system(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "legal-section" in html and "legal-toc" in html
    assert 'class="site-header' in html and 'class="site-footer' in html


def test_privacy_policy_does_not_claim_google_fonts(client):
    """Fonts are self-hosted since m1 — the third-party claim was false."""
    html = client.get("/privacy").get_data(as_text=True)
    assert "Google Fonts" not in html
    assert "fonts.googleapis" not in html


# ---- VAL-CON-004 / VAL-CROSS-005: 404 recovery -----------------------------

def test_unknown_urls_render_branded_404(client):
    resp = client.get("/definitely-not-a-page")
    assert resp.status_code == 404
    html = resp.get_data(as_text=True)
    assert "Page not found" in html
    assert "nf-code" in html  # branded 404 numeral
    # Recovery exits: catalogue, status board, home.
    for href in ('href="/cheats"', 'href="/status"', 'href="/"'):
        assert href in html, href


def test_404_has_no_inline_stylesheet():
    src = open(os.path.join(TPL_DIR, "404.html"), encoding="utf-8").read()
    assert "<style" not in src


# ---- Design-system hygiene -------------------------------------------------

CONTENT_TEMPLATES = ("faq.html", "loader.html", "terms.html", "privacy.html", "404.html")

LEGACY_TOKENS = (
    "--accent-primary", "--accent-soft", "--accent-line", "--accent-deep",
    "--glow-", "--gradient-", "--status-error", "--status-online",
    "--status-warning", "--status-info", "--bg-card", "--border-accent",
    "--shadow-soft", "--ambient-", "--ease-smooth",
)


@pytest.mark.parametrize("rel", CONTENT_TEMPLATES)
def test_content_templates_use_no_legacy_tokens(rel):
    src = open(os.path.join(TPL_DIR, rel), encoding="utf-8").read()
    for token in LEGACY_TOKENS:
        assert token not in src, f"{rel}: {token}"


def test_faq_loader_legal_css_lives_in_site_css():
    """The ported page sections are home in site.css; legacy.css is deleted
    (m3-legacy-deletion), so site.css is their only home."""
    site = open(os.path.join(CSS_DIR, "src", "site.css"), encoding="utf-8").read()
    assert not os.path.exists(os.path.join(CSS_DIR, "src", "legacy.css"))
    for selector in (
        r"^\.faq-question \{", r"^\.loader-card \{", r"^\.legal-toc \{",
        r"^\.nf-chip \{",
    ):
        assert re.search(selector, site, re.M), selector


def test_content_templates_have_no_inline_styles():
    for rel in CONTENT_TEMPLATES:
        src = open(os.path.join(TPL_DIR, rel), encoding="utf-8").read()
        assert "<style" not in src, rel
        assert ' style="' not in src, rel


# ---- Fixtures reused from the catalogue tests ------------------------------

@pytest.fixture
def catalogue(make_product):
    alpha = make_product(
        "rust-alpha", name="Rust Alpha", game="Rust", status="undetected",
        tiers=[("1 Day", 1, 500, False), ("1 Week", 7, 1800, False)],
    )
    make_product(
        "rust-beta", name="Rust Beta", game="Rust", status="updating",
        tiers=[("1 Month", 30, 3900, False)],
    )
    gamma = make_product(
        "cs2-gamma", name="Gamma Legit", game="Counter-Strike 2", status="detected",
        tiers=[("1 Day", 1, 900, False)],
    )
    return {"rust-alpha": alpha, "rust-beta": None, "cs2-gamma": gamma}
