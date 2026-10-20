"""Admin workflow tests (VAL-ADM-005 / VAL-ADM-006).

Covers the critical admin paths the redesign must not break:
- status changes in the tiers editor append StatusEvent history rows
  (status + note + timestamp) feeding the public honesty story
- product create -> tier add -> tier edit
- order fulfillment context renders on the order detail page
- impersonation enter/exit
- settings save round-trip
- JSON product export/import round-trip
"""
import io
import json

import pytest

from models import Order, PricingTier, Product, Setting, StatusEvent


# --- StatusEvent history (VAL-ADM-005) --------------------------------------

def test_status_change_appends_status_event(admin_client, post_form, db, make_product):
    product = make_product(slug="status-ev", status="undetected")

    resp = post_form(admin_client, f"/admin/products/{product.id}/tiers",
                     {"status": "online"})

    assert resp.status_code == 302
    assert product.status == "online"
    events = StatusEvent.query.filter_by(product_id=product.id).all()
    assert len(events) == 1
    ev = events[0]
    assert ev.status == "online"
    assert ev.note, "status change event must carry a human-readable note"
    assert ev.created_at is not None


def test_status_note_field_stored_when_provided(admin_client, post_form, db, make_product):
    product = make_product(slug="status-note", status="undetected")

    resp = post_form(admin_client, f"/admin/products/{product.id}/tiers",
                     {"status": "offline", "status_note": "Detected on Rust, investigating"})

    assert resp.status_code == 302
    ev = StatusEvent.query.filter_by(product_id=product.id).one()
    assert ev.status == "offline"
    assert ev.note == "Detected on Rust, investigating"


def test_unchanged_status_creates_no_event(admin_client, post_form, db, make_product):
    product = make_product(slug="status-same", status="undetected")

    resp = post_form(admin_client, f"/admin/products/{product.id}/tiers",
                     {"status": "undetected"})

    assert resp.status_code == 302
    assert StatusEvent.query.filter_by(product_id=product.id).count() == 0


def test_invalid_status_value_creates_no_event(admin_client, post_form, db, make_product):
    product = make_product(slug="status-bogus", status="undetected")

    resp = post_form(admin_client, f"/admin/products/{product.id}/tiers",
                     {"status": "bogus"})

    assert resp.status_code == 302
    assert product.status == "undetected"
    assert StatusEvent.query.filter_by(product_id=product.id).count() == 0


# --- Workflow smoke: product create -> tier add/edit (VAL-ADM-006) ----------

def test_workflow_create_product_add_and_edit_tier(admin_client, post_form, db):
    resp = post_form(admin_client, "/admin/products/create", {
        "name": "Workflow Test Cheat",
        "slug": "workflow-test",
        "key_source": "pool",
        "visibility": "public",
    })
    assert resp.status_code == 302
    product = Product.query.filter_by(slug="workflow-test").one()

    resp = post_form(admin_client, f"/admin/products/{product.id}/tiers/add", {
        "label": "1 Week",
        "duration_days": 7,
        "price_pounds": "20.00",
        "billing_type": "one_time",
    })
    assert resp.status_code == 302
    tier = PricingTier.query.filter_by(product_id=product.id).one()
    assert tier.label == "1 Week"
    assert tier.duration_days == 7
    assert tier.price_pence == 2000

    resp = post_form(admin_client, f"/admin/tiers/{tier.id}/edit", {
        "label": "7 Days",
        "price_pounds": "25.00",
    })
    assert resp.status_code == 302
    assert tier.label == "7 Days"
    assert tier.price_pence == 2500

    # The tiers editor page renders with the edited tier in place.
    page = admin_client.get(f"/admin/products/{product.id}/tiers")
    assert page.status_code == 200
    assert "7 Days" in page.get_data(as_text=True)


# --- Workflow smoke: order fulfillment context render (VAL-ADM-006) ---------

@pytest.mark.parametrize("order_status", ["pending", "awaiting_keys"])
def test_order_fulfillment_context_renders(admin_client, db, make_product, make_user,
                                           order_status):
    product = make_product(slug="fulfil-prod")
    tier = PricingTier.query.filter_by(product_id=product.id).one()
    buyer = make_user("fulfil_buyer")
    order = Order(user_id=buyer.id, tier_id=tier.id, status=order_status, quantity=2)
    db.session.add(order)
    db.session.commit()

    resp = admin_client.get(f"/admin/orders/{order.id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Fulfillment context is rendered: product, tier, duration, quantity.
    assert product.name in html
    assert tier.label in html
    assert "1 days" in html  # tier.duration_days
    assert "2" in html       # order quantity
    # Awaiting-keys orders surface their fulfillment paths, not "already completed".
    assert "assign-custom" in html or "Assign" in html


def test_orders_list_filters_by_status(admin_client, db, make_product, make_user):
    product = make_product(slug="fulfil-list")
    tier = PricingTier.query.filter_by(product_id=product.id).one()
    buyer = make_user("fulfil_list_buyer")
    db.session.add(Order(user_id=buyer.id, tier_id=tier.id, status="awaiting_keys"))
    db.session.commit()

    resp = admin_client.get("/admin/orders?status=awaiting_keys")
    assert resp.status_code == 200
    assert "awaiting_keys" in resp.get_data(as_text=True)


# --- Workflow smoke: impersonation enter/exit (VAL-ADM-006) -----------------

def test_impersonation_enter_and_exit(admin_client, post_form, db, make_user):
    buyer = make_user("imp_buyer")

    resp = post_form(admin_client, f"/admin/users/{buyer.id}/impersonate", {})
    assert resp.status_code == 302
    # Now viewing the site as the buyer.
    assert admin_client.get("/my-keys").status_code == 200

    resp = admin_client.get("/admin/stop-impersonating")
    assert resp.status_code == 302
    # Back as the admin: the admin dashboard is reachable again.
    assert admin_client.get("/admin/").status_code == 200


# --- Workflow smoke: settings round-trip (VAL-ADM-006) ----------------------

def test_settings_save_round_trip(admin_client, post_form, db):
    resp = post_form(admin_client, "/admin/settings", {
        "chairfbi_api_token": "cf-token-roundtrip",
        "loader_token": "loader-tok-123",
    })
    assert resp.status_code == 302

    assert Setting.get("chairfbi_api_token") == "cf-token-roundtrip"
    assert Setting.get("loader_token") == "loader-tok-123"
    assert admin_client.get("/admin/settings").status_code == 200

    # Posting without a value clears that stored setting; other fields sent
    # again keep their values (an empty field means "clear" by design).
    resp = post_form(admin_client, "/admin/settings", {
        "chairfbi_api_token": "cf-token-roundtrip",
        "loader_token": "",
    })
    assert resp.status_code == 302
    assert Setting.get("loader_token") is None
    assert Setting.get("chairfbi_api_token") == "cf-token-roundtrip"


# --- Workflow smoke: JSON export/import unaffected (VAL-ADM-006) ------------

def test_product_export_import_round_trip(admin_client, post_form, db, make_product):
    make_product(slug="xport-prod", tiers=[("1 Day", 1, 900, False)])

    resp = admin_client.get("/admin/products/export")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    entry = next(e for e in data if e["slug"] == "xport-prod")
    assert entry["tiers"] == [{"label": "1 Day", "duration_days": 1, "price_pence": 900}]

    # Re-importing the export takes the update path (slug already exists).
    payload = io.BytesIO(json.dumps(data).encode("utf-8"))
    resp = post_form(admin_client, "/admin/products/import", {
        "products_file": (payload, "products.json"),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert "Import complete: 0 created, 1 updated." in resp.get_data(as_text=True)
    assert Product.query.filter_by(slug="xport-prod").count() == 1
