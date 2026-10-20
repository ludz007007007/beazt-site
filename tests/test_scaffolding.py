"""Smoke tests proving the shared fixtures work."""


def test_ping(client):
    assert client.get("/ping").data == b"ok"


def test_database_is_isolated_temp_sqlite(app):
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    assert uri.startswith("sqlite:///")
    assert "beazt-tests-" in uri
    assert "instance" not in uri.replace("\\", "/").split("beazt-tests-")[-1]


def test_db_fixture_gives_clean_schema(db):
    from models import Product, User

    assert Product.query.count() == 0
    assert User.query.count() == 0


def test_post_without_csrf_is_rejected(client):
    resp = client.post("/auth/login", data={"username": "x", "password": "y"})
    assert resp.status_code == 400


def test_login_helper_authenticates_buyer(buyer_client):
    resp = buyer_client.get("/my-keys")
    assert resp.status_code == 200


def test_login_with_wrong_password_does_not_redirect(client, make_user, login):
    make_user("someone", "right-password")
    resp = login(client, "someone", "wrong-password")
    assert resp.status_code == 200


def test_admin_client_reaches_admin(admin_client):
    assert admin_client.get("/admin/").status_code in (200, 308)


def test_make_product_factory(db, make_product):
    product = make_product("rust-test", tiers=[("1 Day", 1, 900, False), ("Monthly", 30, 4900, True)])
    tiers = product.tiers.all()
    assert len(tiers) == 2
    assert {t.billing_type for t in tiers} == {"one_time", "subscription"}
