"""Price-entry rounding regression tests (money-path correctness).

int(price * 100) truncates the binary float: entering 19.99 in the admin
tiers editor stored 1998 pence (19.99 * 100 == 1998.999...). These tests
pin the rounded behaviour for add_tier / edit_tier and the fallback tier
constants, and cover sub-penny boundary inputs.
"""
import pytest

from models import PricingTier, Product
from routes.admin import _FALLBACK_TIERS, _PRIVATE_TIERS, _sync_product_tiers


def _product_without_tiers(db, make_product, slug):
    # make_product treats a falsy tiers list as "use the default tier", so
    # delete whatever it seeded to start from a clean slate.
    product = make_product(slug=slug, tiers=[])
    PricingTier.query.filter_by(product_id=product.id).delete()
    db.session.commit()
    return product


def _add_tier(admin_client, post_form, product, price, **kwargs):
    data = {
        "label": "1 Week",
        "duration_days": 7,
        "price_pounds": price,
        "billing_type": "one_time",
    }
    return post_form(admin_client, f"/admin/products/{product.id}/tiers/add", data, **kwargs)


def test_add_tier_19_99_stores_1999(admin_client, post_form, db, make_product):
    product = _product_without_tiers(db, make_product, "round-1999")
    resp = _add_tier(admin_client, post_form, product, "19.99")
    assert resp.status_code == 302
    tier = PricingTier.query.filter_by(product_id=product.id).one()
    assert tier.price_pence == 1999


def test_edit_tier_19_99_stores_1999(admin_client, post_form, db, make_product):
    product = make_product(slug="round-edit", tiers=[("1 Week", 7, 1500, False)])
    tier = PricingTier.query.filter_by(product_id=product.id).one()
    resp = post_form(admin_client, f"/admin/tiers/{tier.id}/edit", {
        "price_pounds": "19.99",
    })
    assert resp.status_code == 302
    assert tier.price_pence == 1999


def test_add_tier_0_10_stores_10(admin_client, post_form, db, make_product):
    product = _product_without_tiers(db, make_product, "round-010")
    resp = _add_tier(admin_client, post_form, product, "0.10")
    assert resp.status_code == 302
    tier = PricingTier.query.filter_by(product_id=product.id).one()
    assert tier.price_pence == 10


def test_add_tier_299_00_stores_29900(admin_client, post_form, db, make_product):
    product = _product_without_tiers(db, make_product, "round-299")
    resp = _add_tier(admin_client, post_form, product, "299.00")
    assert resp.status_code == 302
    tier = PricingTier.query.filter_by(product_id=product.id).one()
    assert tier.price_pence == 29900


def test_add_tier_subpenny_price_rejected(admin_client, post_form, db, make_product):
    """0.005 rounds to 0 pence — a free tier must not be creatable."""
    product = _product_without_tiers(db, make_product, "round-subpenny")
    resp = _add_tier(admin_client, post_form, product, "0.005", follow_redirects=True)
    assert resp.status_code == 200
    assert PricingTier.query.filter_by(product_id=product.id).count() == 0
    assert "must be positive" in resp.get_data(as_text=True)

def test_edit_tier_subpenny_price_rejected(admin_client, post_form, db, make_product):
    """0.005 on edit must not zero out the existing price."""
    product = make_product(slug="round-edit-sub", tiers=[("1 Week", 7, 1500, False)])
    tier = PricingTier.query.filter_by(product_id=product.id).one()
    resp = post_form(admin_client, f"/admin/tiers/{tier.id}/edit", {
        "price_pounds": "0.005",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert tier.price_pence == 1500
    assert "positive amount" in resp.get_data(as_text=True)


def test_edit_tier_blank_price_leaves_value(admin_client, post_form, db, make_product):
    """No price_pounds in the form = no price change (existing behaviour)."""
    product = make_product(slug="round-blank", tiers=[("1 Week", 7, 1500, False)])
    tier = PricingTier.query.filter_by(product_id=product.id).one()
    resp = post_form(admin_client, f"/admin/tiers/{tier.id}/edit", {
        "label": "7 Days",
    })
    assert resp.status_code == 302
    assert tier.price_pence == 1500
    assert tier.label == "7 Days"


def test_fallback_tier_constants_store_exact_pence(db):
    """_sync_product_tiers uses the same conversion — constants must land on
    their exact pence values, not truncation artifacts."""
    assert [(label, int(round(price * 100))) for label, days, price in _FALLBACK_TIERS] == [
        ("1 Day", 572),
        ("3 Days", 1474),
        ("7 Days", 2156),
        ("30 Days", 4140),
    ]
    assert [(label, int(round(price * 100))) for label, days, price, sub in _PRIVATE_TIERS] == [
        ("1 Month", 4999),
        ("12 Months", 39999),
    ]

    for visibility, expected in (
        ("public", {572, 1474, 2156, 4140}),
        ("private", {4999, 39999}),
    ):
        product = Product(name="Sync Rounding", slug=f"sync-round-{visibility}",
                          visibility=visibility, key_source="pool", status="undetected")
        db.session.add(product)
        db.session.commit()
        _sync_product_tiers(product)
        pences = {t.price_pence for t in
                  PricingTier.query.filter_by(product_id=product.id).all()}
        assert pences == expected
