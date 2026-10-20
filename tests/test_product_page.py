"""Product page rebuild (m2-product-page): VAL-ST-003 / VAL-ST-005 / VAL-ST-006
/ VAL-ST-010 / VAL-FUN-005 / VAL-RSP-003.

Source assertions over templates/product.html + rendered behaviour over the
Flask test client. Every expectation is computed from inserted rows — no
hardcoded dates, prices or statuses.
"""

import os
import re
from datetime import date, datetime
from html.parser import HTMLParser

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "templates", "product.html")
APP_PY = os.path.join(ROOT, "app.py")
SCRIPT_JS = os.path.join(ROOT, "static", "js", "script.js")
COMPONENTS_CSS = os.path.join(ROOT, "static", "css", "src", "components.css")
STYLE_CSS = os.path.join(ROOT, "static", "css", "style.css")


def _src():
    with open(TEMPLATE, encoding="utf-8") as fh:
        return fh.read()


def _main(html):
    start = html.index("<main")
    return html[start:html.index("</main>", start)]


def _text(fragment):
    import html as html_mod
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_mod.unescape(fragment))).strip()


def _today_variants():
    today = date.today()
    return {
        today.strftime("%A, %B %d, %Y"),
        today.strftime("%d %b %Y"),
        f"{today.day} {today.strftime('%b %Y')}",
        today.strftime("%Y-%m-%d"),
    }


@pytest.fixture
def product(make_product):
    return make_product(
        "page-product",
        name="Page Product",
        game="Rust",
        tiers=[("1 Day", 1, 900, False), ("1 Week", 7, 4900, False), ("1 Month", 30, 9900, False)],
    )


# ---- VAL-ST-010: no inline stylesheet, lean page, clean markup -------------

def test_no_style_block_in_product_template():
    src = _src()
    assert "<style" not in src, "product.html must not carry an inline stylesheet"


def test_no_inline_style_or_event_handler_attributes():
    src = _src()
    assert "style=" not in src, "no inline style= attributes anywhere on the page"
    assert not re.search(r"\son[a-z]+=", src), "no inline on* handlers (Alpine x-/@ only)"


def test_page_line_budget():
    lines = _src().count("\n") + 1
    # ~400 target; the preserved checkout wire-protocol script block (~90
    # lines) plus head/JSON-LD account for the rest.
    assert lines <= 500, f"product.html is {lines} lines"


def test_no_render_time_date_processor():
    """The honesty rule: freshness labels come from DB data only. The old
    inject_verified_date context processor (render-time 'Updated <today>')
    is gone and no template consumes it."""
    with open(APP_PY, encoding="utf-8") as fh:
        app_src = fh.read()
    assert "def inject_verified_date" not in app_src
    assert "verified_today" not in _src()
    for name in os.listdir(os.path.join(ROOT, "templates")):
        if not name.endswith(".html"):
            continue
        with open(os.path.join(ROOT, "templates", name), encoding="utf-8") as fh:
            assert "verified_today" not in fh.read(), name


# ---- VAL-ST-003: real freshness dates, consistent with the catalogue card --

def test_freshness_date_matches_db_and_catalogue(client, db, product):
    product.last_verified_at = datetime(2024, 1, 15, 12, 0)
    db.session.commit()
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    assert "15 Jan 2024" in page
    assert "Last verified 15 Jan 2024" in page
    for variant in _today_variants():
        assert variant not in page, variant
    # Same derivation as the catalogue card for the same product.
    cheats = client.get("/cheats").get_data(as_text=True)
    card = cheats[cheats.index('href="/product/page-product"'):]
    card = card[:card.index("</article>")]
    assert "Last verified 15 Jan 2024" in card


def test_freshness_falls_back_to_status_event(client, db, product):
    from models import StatusEvent

    db.session.add(StatusEvent(product_id=product.id, status="updating",
                               created_at=datetime(2025, 3, 2, 9, 0)))
    db.session.commit()
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    assert "2 Mar 2025" in page


def test_unverified_product_has_no_date_stamp(client, product):
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    assert "Not yet verified" in page
    for variant in _today_variants():
        assert variant not in page, variant


# ---- VAL-ST-004: unified status taxonomy on the product page ---------------

def test_status_pill_uses_shared_taxonomy(client, product):
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    assert 'class="status-pill status-pill--undetected"' in page
    assert ">Undetected<" in page
    assert "UNDETECTED" not in page


def test_availability_badge_separate_from_status(client, db, product):
    from models import Key

    product.key_source = "pool"
    db.session.add(Key(product_id=product.id, key_value="POOL-1", is_active=False))
    db.session.commit()
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    assert "badge-availability--in_stock" in page
    assert ">In stock<" in page
    # Sold out: pool emptied
    db.session.query(Key).filter_by(product_id=product.id).delete()
    db.session.commit()
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    assert "badge-availability--sold_out" in page
    assert ">Sold out<" in page


# ---- VAL-ST-005: decision-ready pricing panel ------------------------------

def test_plan_ladder_labels_one_time_vs_recurring(client, make_product):
    make_product("recurring-product", tiers=[("Weekly", 7, 999, True), ("Monthly", 30, 2999, True)])
    page = _main(client.get("/product/recurring-product").get_data(as_text=True))
    ladder = page[page.index("plan-ladder"):page.index("pd-empty-plans")]
    text = _text(ladder)
    assert "Recurring" in text
    assert "One-time" not in text


def test_plan_ladder_per_day_math_and_duration(client, product):
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    text = _text(page)
    # 900p / 1 day = £9.00/day; 4900p / 7 = £7.00/day; 9900p / 30 = £3.30/day
    for expected in ("£9.00/day", "£7.00/day", "£3.30/day"):
        assert expected in text, expected
    assert "One-time · 1 day" in text
    assert "One-time · 7 days" in text
    assert "One-time · 30 days" in text
    assert "1 days" not in text, "singular durations must read '1 day', never '1 days'"


def test_best_value_marker_on_cheapest_per_day_plan(client, product):
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    ladder = page[page.index("plan-ladder"):]
    ladder = ladder[:ladder.index("pd-empty-plans")]
    rows = re.findall(r'<label class="plan-row[^"]*".*?</label>', ladder, re.S)
    assert len(rows) == 3
    best = [r for r in rows if "Best value" in r]
    assert len(best) == 1, "exactly one best-value marker"
    assert "£3.30/day" in best[0], "marker lands on the cheapest per-day plan"
    assert "Best value" not in "".join(r for r in rows if "£3.30/day" not in r)


def test_quantity_explains_keys_per_order(client, product):
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    assert "Keys per order — each key is a separate licence." in page


def test_gateway_minimums_surfaced_upfront(client, product, monkeypatch):
    monkeypatch.setattr(
        "routes.main.get_ivno_config",
        lambda: {"api_key": "", "api_secret": "", "webhook_secret": ""},
    )
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    text = _text(page)
    assert "No minimum" in text
    assert "Min £20" in text
    assert "temporarily unavailable" in text
    assert "contact support" in text
    assert "cardEnabled: false" in page
    # The card radio is server-side bound to the availability flag, PayFast
    # is never disabled.
    assert ':disabled="cardUnavailable"' in page
    assert 'value="payfast" x-model="selectedGateway" aria-label="Pay with PayFast">' in page


def test_pricing_panel_states_reach_mobile_bar(client, product):
    """The mobile bar mirrors the panel (same selected plan + price)."""
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    bar = page[page.index('class="mobile-buy-bar"'):]
    assert "currentPrice.toFixed(2)" in bar
    assert "currentVariant ? currentVariant.label" in bar


# ---- Regression (m2 scrutiny r1): mixed product, subscription default -------
#
# base.css enforces [hidden]{display:none!important} and Alpine's :class
# binding only toggles CLASSES — it can never remove a server-rendered static
# `hidden` attribute. On mixed one-time/subscription products whose route
# default tier is a subscription, the quantity and payment-method blocks
# shipped exactly that static attribute, so switching to a one-time plan left
# no visible buy control (money-path dead end). Both blocks must keep the
# static `hidden` as the no-JS initial state AND carry a `:hidden` attribute
# binding (the tab-panel pattern) so Alpine can reveal them.

class _TagsWith(HTMLParser):
    """Collects (tag, attrs) for start tags matching a predicate."""

    def __init__(self, predicate):
        super().__init__(convert_charrefs=True)
        self.predicate = predicate
        self.matches = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if self.predicate(tag, attr):
            self.matches.append((tag, attr))


def _mixed_sub_default_product(db, make_product):
    """Mixed product whose route-default tier (duration_days == 30) is a
    subscription WITH an external link — the scrutiny-r1 dead-end shape
    (seeded equivalents: rust-full-suite, apex-esp)."""
    from models import PricingTier

    product = make_product(
        "mixed-sub-default",
        tiers=[("1 Day", 1, 900, False), ("Monthly", 30, 2999, True), ("Lifetime", 3650, 29900, False)],
    )
    PricingTier.query.filter_by(product_id=product.id, billing_type="subscription").update(
        {"ivno_subscription_link": "https://ivno.invalid/subscribe/demo"}
    )
    db.session.commit()
    return product


class TestMixedProductPlanSwitchReveal:
    def _quantity_block(self, page):
        parser = _TagsWith(lambda t, a: t == "div" and "pd-quantity" in (a.get("class") or ""))
        parser.feed(page)
        assert len(parser.matches) == 1, "quantity block not found"
        return parser.matches[0][1]

    def _payment_block(self, page):
        parser = _TagsWith(
            lambda t, a: t == "div" and (a.get(":class") or "") == "!hasExternalSub ? '' : 'is-hidden'"
        )
        parser.feed(page)
        assert len(parser.matches) == 1, "payment-method block not found"
        return parser.matches[0][1]

    def test_sub_default_blocks_have_static_hidden_and_alpine_binding(self, buyer_client, db, make_product):
        _mixed_sub_default_product(db, make_product)
        page = _main(buyer_client.get("/product/mixed-sub-default").get_data(as_text=True))

        qty = self._quantity_block(page)
        assert "hidden" in qty, "static hidden no-JS fallback missing on quantity block"
        assert qty.get(":hidden") == "!(currentVariant && !isSubscription)", (
            "quantity block needs the :hidden attribute binding (:class can't remove the static attr)"
        )

        pay = self._payment_block(page)
        assert "hidden" in pay, "static hidden no-JS fallback missing on payment block"
        assert pay.get(":hidden") == "hasExternalSub", (
            "payment block needs the :hidden attribute binding (:class can't remove the static attr)"
        )

        # Revealing the payment block must restore the buy control itself:
        # the authenticated submit button renders INSIDE that block.
        assert page.index(':hidden="hasExternalSub"') < page.index('type="submit"') < page.index("pd-subscribe")

    def test_one_time_default_blocks_visible_but_still_bound(self, buyer_client, product):
        """One-time default: blocks render visible server-side (no static
        hidden) yet still carry the :hidden binding so Alpine can hide them
        when the buyer switches TO a subscription plan."""
        page = _main(buyer_client.get("/product/page-product").get_data(as_text=True))
        qty = self._quantity_block(page)
        assert "hidden" not in qty
        assert qty.get(":hidden") == "!(currentVariant && !isSubscription)"
        pay = self._payment_block(page)
        assert "hidden" not in pay
        assert pay.get(":hidden") == "hasExternalSub"


# ---- VAL-ST-006: keyboard-operable tabs and gallery ------------------------

def test_tabs_implement_aria_pattern(client, product):
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    assert 'role="tablist"' in page
    assert page.count('role="tab"') == 3
    assert page.count('role="tabpanel"') == 3
    # Roving tabindex server-rendered: first tab in tab order, others -1.
    assert 'id="tab-overview" aria-controls="panel-overview" aria-selected="true" tabindex="0"' in page
    assert page.count('tabindex="-1"') >= 2
    for tab, panel in (("overview", "panel-overview"), ("features", "panel-features"), ("buyer", "panel-buyer")):
        assert f'aria-controls="{panel}"' in page
        assert f'id="{panel}" role="tabpanel" aria-labelledby="tab-{tab}"' in page


def test_tabs_keyboard_handler_lives_in_script():
    with open(SCRIPT_JS, encoding="utf-8") as fh:
        js = fh.read()
    assert "onTablistKeydown" in js
    for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
        assert key in js, key


# ---- Regression (m2 user-testing r1, VAL-ST-006): tab panels must render ----
#
# components.css used to default `.tab-panel{display:none}`, countered only by
# `.is-active`/`.active` classes that NOTHING ever applied to a panel (the
# template binds `:hidden` only; script.js tabsState.select only sets
# activeTab). Result: every panel — including the server-rendered Overview —
# stayed display:none with 0px height while all ARIA tab mechanics worked.
# Panel visibility is now attribute-driven ONLY: the active panel ships
# without the hidden attribute; inactive panels keep the static hidden
# (no-JS fallback) plus the Alpine :hidden binding that reveals them, and
# base.css `[hidden]{display:none!important}` does the hiding.

def test_tab_panel_css_has_no_display_none_default():
    """CSS-source regression: no rule may hide .tab-panel via display:none —
    the hidden attribute already hides inactive panels, and a CSS default
    would hide the active panel too."""
    for path in (COMPONENTS_CSS, STYLE_CSS):
        with open(path, encoding="utf-8") as fh:
            css = fh.read()
        hiding = [
            selectors.strip()
            for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
            if ".tab-panel" in selectors and "display:none" in body.replace(" ", "")
        ]
        assert not hiding, (
            f"{os.path.basename(path)}: {hiding} hides .tab-panel; visibility "
            "must stay attribute-driven ([hidden] + Alpine :hidden bindings)"
        )


def test_tab_panel_visibility_is_attribute_driven(client, product):
    """The ACTIVE panel ships visible (no static hidden — the no-JS default
    renders Overview) and every panel carries the Alpine :hidden binding;
    inactive panels keep the static hidden fallback."""
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    parser = _TagsWith(lambda t, a: t == "div" and "tab-panel" in (a.get("class") or ""))
    parser.feed(page)
    panels = {attrs["id"]: attrs for _, attrs in parser.matches}
    assert set(panels) == {"panel-overview", "panel-features", "panel-buyer"}

    assert "hidden" not in panels["panel-overview"], (
        "active panel must render server-side (no-JS default) — it is the "
        "only panel visible before Alpine boots"
    )
    assert panels["panel-overview"].get(":hidden") == "activeTab !== 'overview'"
    for pid in ("panel-features", "panel-buyer"):
        assert "hidden" in panels[pid], f"{pid}: static hidden no-JS fallback missing"
        assert ":hidden" in panels[pid], f"{pid}: Alpine :hidden binding missing"


def test_gallery_thumbs_are_keyboard_selectable_buttons(client, db, product):
    product.gallery_images = '["/static/images/products/page-product/a.png", "/static/images/products/page-product/b.png"]'
    db.session.commit()
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    thumbs = re.findall(r'<button type="button" class="pd-thumb".*?</button>', page, re.S)
    assert len(thumbs) == 2, "thumbnails must be real <button> elements"
    for t in thumbs:
        assert ":aria-pressed" in t
        assert "@click" in t
        assert 'loading="lazy"' in t
    assert 'role="status" x-text="announcement"' in page


def test_gallery_images_carry_intrinsic_dimensions(client, product):
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    mains = re.findall(r'<img class="pd-gallery__main"[^>]*>', page)
    # The generated cover PNG is 1200x675 (16:9); the markup must match its
    # intrinsic size so there is no layout shift.
    assert mains and 'width="1200" height="675"' in mains[0]


# ---- VAL-FUN-005 / VAL-RSP-003: wire protocol + keyboard path --------------

def test_authenticated_buy_uses_wire_protocol(buyer_client, product):
    page = _main(buyer_client.get("/product/page-product").get_data(as_text=True))
    assert "window.BEAZT_PRODUCT" in page
    assert "isAuthenticated: true" in page
    assert "'/checkout/create-session'" in page
    for field in ("tier_id", "quantity", "gateway", "csrf_token"):
        assert f"formData.append('{field}'" in page
    assert '@submit.prevent="handleCheckout()"' in page
    assert ":disabled=\"!canBuy || checkingOut\"" in page


def test_keyboard_path_reaches_every_money_control(client, product):
    """Nothing on the money path is unreachable by keyboard: plan radios,
    quantity stepper, gateway radios and the sign-in CTA are all native
    focusable elements, and no positive tabindex breaks the tab order."""
    page = _main(client.get("/product/page-product").get_data(as_text=True))
    assert page.count('type="radio"') >= 5  # 3 plans + 2 gateways
    assert 'class="pd-qty-input"' in page
    assert 'href="/auth/login?next=/product/page-product"' in page
    assert not re.search(r'tabindex="[1-9]', page), "no positive tabindex"
