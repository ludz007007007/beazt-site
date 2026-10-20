"""Tests for scripts/seed_demo.py: production guard + idempotent demo data."""

import importlib.util
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def seed_module():
    path = os.path.join(ROOT, "scripts", "seed_demo.py")
    spec = importlib.util.spec_from_file_location("seed_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("url", [
    None,
    "",
    "sqlite:///instance/beazt.db",
    "sqlite:///C:/tmp/beazt.db",
    "sqlite://",
    "mysql+pymysql://root:pw@localhost/beazt",
    "mysql+pymysql://root:pw@127.0.0.1:3306/beazt_dev",
    "postgresql://u:p@[::1]/beazt",
])
def test_local_database_urls_are_allowed(seed_module, url):
    ok, reason = seed_module.check_database_url(url, env={})
    assert ok, reason


@pytest.mark.parametrize("url", [
    "mysql+pymysql://beazt:secret@db.example.com/beazt",
    "mysql+pymysql://beazt:secret@10.0.0.5/beazt",
    "postgresql://u:p@prod-db.internal:5432/beazt",
    "mysql+pymysql://root:pw@localhost/beazt_production",
    "sqlite:////var/www/prod/beazt.db",
])
def test_production_looking_urls_are_refused(seed_module, url):
    ok, reason = seed_module.check_database_url(url, env={})
    assert not ok
    assert reason


@pytest.mark.parametrize("env", [
    {"VERCEL": "1"},
    {"FLASK_ENV": "production"},
    {"APP_ENV": "production"},
])
def test_production_environment_markers_are_refused(seed_module, env):
    ok, _ = seed_module.check_database_url("sqlite:///instance/beazt.db", env=env)
    assert not ok


def _counts():
    from models import Key, Order, PricingTier, Product, Review, StatusEvent, User

    return {m.__name__: m.query.count() for m in (Product, PricingTier, Key, User, Order, Review, StatusEvent)}


def test_seed_populates_demo_data(db, seed_module):
    from models import Key, Order, Product, Review, StatusEvent, User

    seed_module.seed_demo_data()

    products = Product.query.all()
    assert 4 <= len(products) <= 6
    assert len({p.game for p in products}) >= 2
    assert {"undetected", "updating", "detected"} <= {p.status for p in products}

    tiers = [t for p in products for t in p.tiers]
    assert any(t.is_subscription and t.billing_type == "subscription" for t in tiers)
    assert any(not t.is_subscription and t.billing_type == "one_time" for t in tiers)

    assert Key.query.filter(Key.user_id.is_(None), Key.order_id.is_(None)).count() > 0

    admin = User.query.filter_by(username=seed_module.DEMO_ADMIN[0]).one()
    buyer = User.query.filter_by(username=seed_module.DEMO_BUYER[0]).one()
    assert admin.is_admin and admin.check_password(seed_module.DEMO_ADMIN[1])
    assert not buyer.is_admin and buyer.check_password(seed_module.DEMO_BUYER[1])

    assert Order.query.filter_by(status="completed").count() >= 1
    assert Order.query.filter_by(status="pending").count() >= 1
    assert Review.query.filter_by(status="approved").count() >= 1
    assert Review.query.filter_by(status="pending").count() >= 1

    for p in products:
        latest = StatusEvent.query.filter_by(product_id=p.id).order_by(StatusEvent.created_at.desc()).first()
        assert latest is not None, p.slug
        assert latest.status == p.status


def test_seed_is_idempotent(db, seed_module):
    seed_module.seed_demo_data()
    first = _counts()
    seed_module.seed_demo_data()
    assert _counts() == first


def test_seed_gives_demo_products_multi_image_galleries(db, seed_module):
    """1-2 demo products carry a multi-image gallery (cover URLs) so the
    product page thumbnail strip is browser-verifiable, not just pytest-
    verifiable (m2-art-direction)."""
    from models import Product

    seed_module.seed_demo_data()
    for slug in ("rust-esp-lite", "cs2-legit-assist"):
        product = Product.query.filter_by(slug=slug).one()
        images = json.loads(product.gallery_images)
        assert len(images) >= 2, slug
        assert all(img.startswith("/cheat-image/") for img in images), slug
    # And no demo product still points at the shared Rust placeholder.
    for product in Product.query.all():
        assert product.image_url != "/static/icons/rust_placeholder.jpg", product.slug


def test_seed_gallery_is_idempotent_and_never_overwrites(db, seed_module, monkeypatch):
    from models import Product

    seed_module.seed_demo_data()
    product = Product.query.filter_by(slug="rust-esp-lite").one()
    product.gallery_images = json.dumps(["/static/images/hero.webp"])
    from models import db as _db

    _db.session.commit()
    seed_module.seed_demo_data()
    assert json.loads(product.gallery_images) == ["/static/images/hero.webp"]


def test_seed_writes_synthetic_payfast_settings_only_when_empty(db, seed_module, monkeypatch):
    from models import Setting

    monkeypatch.setenv("PAYFAST_MERCHANT_ID", "99999901")
    Setting.set("payfast_passphrase", "already-configured")
    seed_module.seed_demo_data()
    assert Setting.get("payfast_merchant_id") == "99999901"
    assert Setting.get("payfast_passphrase") == "already-configured"
