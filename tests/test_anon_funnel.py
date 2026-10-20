"""Anonymous purchase funnel (VAL-FUN-001 / VAL-FUN-002).

The product page purchase panel and the mobile sticky buy bar must give
anonymous visitors a real path forward: login/signup links carrying
``next=<product path>``, never a dead disabled button, and no checkout form
at all so no doomed POST to ``/checkout/create-session`` can fire.

For authenticated visitors the Alpine checkout wire protocol
(``window.BEAZT_PRODUCT`` + ``productState().handleCheckout``) must render
exactly as before.
"""

import os
import re
from html.parser import HTMLParser
from urllib.parse import unquote, quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCT_PATH = "/product/anon-funnel-product"
TIERS = [("1 Day", 1, 900, False), ("30 Day", 30, 2499, False)]


def _get(client):
    resp = client.get(PRODUCT_PATH)
    assert resp.status_code == 200, resp.status_code
    return resp.get_data(as_text=True)


def _hrefs(html):
    return [unquote(h) for h in re.findall(r'href="([^"]+)"', html)]


def _anchor_tags(html):
    return re.findall(r"<a\b[^>]*>", html)


def _panel(html):
    m = re.search(r'<aside class="purchase-panel".*?</aside>', html, re.S)
    assert m, "purchase panel not found"
    return m.group(0)


def _bar_tail(html):
    """Markup from the mobile buy bar to the end of the document."""
    assert 'class="mobile-buy-bar"' in html, "mobile buy bar not found"
    return html.split('class="mobile-buy-bar"', 1)[1]


VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class _AnchorChains(HTMLParser):
    """Collects the ancestor chain of every <a> whose href matches target."""

    def __init__(self, target):
        super().__init__(convert_charrefs=True)
        self.target = target
        self.stack = []
        self.chains = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "a" and unquote(attr.get("href", "")) == self.target:
            self.chains.append(list(self.stack) + [(tag, attr)])
        if tag not in VOID_TAGS:
            self.stack.append((tag, attr))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def _anchor_chains(html, href):
    parser = _AnchorChains(href)
    parser.feed(html)
    return parser.chains


class TestAnonymousPanel:
    def test_login_link_carries_product_path(self, client, make_product):
        make_product(slug="anon-funnel-product", tiers=TIERS)
        hrefs = _hrefs(_get(client))
        assert f"/auth/login?next={PRODUCT_PATH}" in hrefs

    def test_signup_link_carries_product_path(self, client, make_product):
        make_product(slug="anon-funnel-product", tiers=TIERS)
        hrefs = _hrefs(_get(client))
        assert f"/auth/signup?next={PRODUCT_PATH}" in hrefs

    def test_login_cta_styled_as_primary_button(self, client, make_product):
        make_product(slug="anon-funnel-product", tiers=TIERS)
        html = _get(client)
        target = f'href="/auth/login?next={PRODUCT_PATH}"'
        assert any(
            "btn-primary" in tag and "btn-block" in tag and target in unquote(tag)
            for tag in _anchor_tags(html)
        ), "sign-in CTA must be an <a> styled as the primary button"

    def test_no_dead_disabled_buy_button(self, client, make_product):
        make_product(slug="anon-funnel-product", tiers=TIERS)
        panel = _panel(_get(client))
        assert "<form" not in panel, "anonymous panel must not render a checkout form"
        assert 'type="submit"' not in panel
        assert "Sign in to buy" in panel

    def test_no_checkout_submit_bindings_on_page(self, client, make_product):
        """No doomed requests: nothing on the anonymous page can fire the
        create-session POST (form submit handler and requestSubmit hook both
        absent)."""
        make_product(slug="anon-funnel-product", tiers=TIERS)
        html = _get(client)
        assert '@submit.prevent="handleCheckout()"' not in html
        assert "requestSubmit" not in html

    def test_wire_protocol_script_still_present(self, client, make_product):
        """The BEAZT_PRODUCT protocol block renders for anon too (state
        contract preserved); only the form action is gated."""
        make_product(slug="anon-funnel-product", tiers=TIERS)
        html = _get(client)
        assert "window.BEAZT_PRODUCT" in html
        assert "isAuthenticated: false" in html
        assert "window.productState" in html


class TestAnonymousMobileBar:
    def test_bar_is_a_login_link_not_a_button(self, client, make_product):
        make_product(slug="anon-funnel-product", tiers=TIERS)
        tail = _bar_tail(_get(client))
        assert "<button" not in tail, "anonymous mobile bar must not render a button"
        assert f'href="/auth/login?next={PRODUCT_PATH}"' in unquote(tail)

    def test_bar_link_styled_as_primary_button(self, client, make_product):
        make_product(slug="anon-funnel-product", tiers=TIERS)
        tail = unquote(_bar_tail(_get(client)))
        m = re.search(r"<a\b[^>]*>", tail)
        assert m and "btn-primary" in m.group(0)


class TestAuthenticatedProtocolPreserved:
    def test_panel_renders_checkout_form_exactly(self, buyer_client, make_product):
        make_product(slug="anon-funnel-product", tiers=TIERS)
        html = _get(buyer_client)
        assert "window.BEAZT_PRODUCT" in html
        assert "isAuthenticated: true" in html
        panel = _panel(html)
        assert '@submit.prevent="handleCheckout()"' in panel
        assert ':disabled="!canBuy || checkingOut"' in panel
        assert "'/checkout/create-session'" in html
        # No auth links leak into the authenticated panel.
        assert f"/auth/login?next={PRODUCT_PATH}" not in _hrefs(panel)

    def test_mobile_bar_keeps_checkout_button(self, buyer_client, make_product):
        make_product(slug="anon-funnel-product", tiers=TIERS)
        tail = _bar_tail(_get(buyer_client))
        assert "<button" in tail
        assert "requestSubmit()" in tail
        assert f"/auth/login?next={PRODUCT_PATH}" not in unquote(tail)


class TestLoginReturnJourney:
    def test_login_with_next_lands_back_on_product(self, client, db, make_user, make_product, post_form):
        make_user("journey_buyer", "password123")
        make_product(slug="anon-funnel-product", tiers=TIERS)
        # The panel link points at /auth/login?next=<product>; the login form
        # posts back to that same URL, so next must survive into the redirect.
        resp = post_form(
            client,
            f"/auth/login?next={PRODUCT_PATH}",
            {"username": "journey_buyer", "password": "password123"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(PRODUCT_PATH)

    def test_returned_buyer_sees_active_buy_button(self, client, db, make_user, make_product, post_form):
        make_user("journey_buyer", "password123")
        make_product(slug="anon-funnel-product", tiers=TIERS)
        post_form(
            client,
            f"/auth/login?next={PRODUCT_PATH}",
            {"username": "journey_buyer", "password": "password123"},
        )
        panel = _panel(_get(client))
        assert '@submit.prevent="handleCheckout()"' in panel


class TestTemplateSource:
    def test_product_template_guest_cta_is_a_real_link(self):
        """Source guard: the anonymous CTA is markup-level links (works
        without JS), not an Alpine-disabled button."""
        src = open(
            os.path.join(ROOT, "templates", "product.html"), encoding="utf-8"
        ).read()
        assert "Sign in to buy" in src
        assert "url_for('auth.login', next='/product/' ~ product.slug)" in src
        assert "url_for('auth.signup', next='/product/' ~ product.slug)" in src


class TestGuestCtaNotHiddenBySubscriptionBranch:
    """Regression: the guest CTA must sit OUTSIDE the payment-method block.
    That block carries ``:class="!hasExternalSub ? '' : 'is-hidden'"`` and
    Alpine hides it when the selected tier is an external subscription —
    nesting the only anonymous path inside it buried the CTA (height 0)."""

    def _external_sub_product(self, db, make_product):
        from models import PricingTier

        product = make_product(
            slug="anon-funnel-product",
            tiers=[("Weekly", 7, 999, True), ("Monthly", 30, 2999, True)],
        )
        # Route selects the 30-day tier; give every tier an external link so
        # hasExternalSub is true client-side.
        PricingTier.query.filter_by(product_id=product.id).update(
            {"ivno_subscription_link": "https://ivno.invalid/subscribe/demo"}
        )
        db.session.commit()
        return product

    def test_guest_cta_outside_hidden_payment_branch(self, client, db, make_product):
        self._external_sub_product(db, make_product)
        html = _get(client)
        chains = _anchor_chains(html, f"/auth/login?next={PRODUCT_PATH}")
        assert chains, "guest CTA missing on external-subscription product"
        for chain in chains:
            for _tag, attrs in chain[:-1]:
                assert "hasExternalSub" not in (attrs.get(":class") or ""), (
                    "guest CTA nested inside the hasExternalSub-controlled block"
                )
                assert "is-hidden" not in (attrs.get("class") or ""), (
                    "guest CTA nested inside an is-hidden element"
                )

    def test_guest_cta_visible_on_plain_product_too(self, client, make_product):
        make_product(slug="anon-funnel-product", tiers=TIERS)
        html = _get(client)
        chains = _anchor_chains(html, f"/auth/login?next={PRODUCT_PATH}")
        assert chains
        for chain in chains:
            for _tag, attrs in chain[:-1]:
                assert "is-hidden" not in (attrs.get("class") or "")
