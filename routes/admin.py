from functools import wraps
import secrets
import re
import json
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app, Response
from flask_login import login_required, current_user, login_user, logout_user
from models import db, User, Product, PricingTier, Order, Key, Setting, Review, StatusEvent
from config import Config, get_chairfbi_config, get_loader_config, get_discord_config, get_ivno_config, get_license_api_config, get_mailer_config

admin_bp = Blueprint("admin", __name__)
logger = logging.getLogger(__name__)

# Admin-facing labels for the raw status values stored on Product.status
# (the tiers editor select shows these exact words).
_ADMIN_STATUS_LABELS = {
    "undetected": "Undetected",
    "online": "Online",
    "offline": "Offline",
    "maintenance": "Maintenance",
}


def _enrich_product_from_venomcheats(product, vc_products=None):
    """Auto-enrich a Product with VenomCheats data if name matches.

    Args:
        product: Product model instance to enrich.
        vc_products: Optional pre-fetched dict {slug: product_data} or list of product dicts.
                     If None, fetches from VenomCheats homepage.
    """
    try:
        from utils.venomcheats import (
            match_chairfbi_to_venom,
            get_all_products,
            find_product_by_slug,
            build_features_text,
            build_description,
            get_primary_image_url,
            download_product_media,
        )

        slug = product.venomcheats_slug or match_chairfbi_to_venom(product.name)
        if not slug:
            return False

        if vc_products is None:
            vc_products = get_all_products()
        if not vc_products:
            return False

        if isinstance(vc_products, dict):
            vc_data = vc_products.get(slug)
        else:
            vc_data = find_product_by_slug(vc_products, slug)
        if not vc_data:
            return False

        product.venomcheats_slug = slug
        product.venomcheats_data = json.dumps(vc_data, ensure_ascii=False)
        product.last_synced_at = datetime.utcnow()
        product.features_text = build_features_text(vc_data)
        product.description = build_description(vc_data)
        # Backend-set artwork wins: only fill image/gallery from VenomCheats
        # when the product has none, so a manual upload or URL in
        # Admin -> Tiers -> Product Content is never clobbered by a sync.
        if not product.image_url:
            product.image_url = get_primary_image_url(vc_data)

        static_dir = os.path.join(current_app.root_path, "static")
        gallery_paths = download_product_media(vc_data, static_dir)
        if gallery_paths and not product.gallery_images:
            product.gallery_images = json.dumps(gallery_paths)

        db.session.commit()
        _backup_products_safe()
        logger.info("Enriched product '%s' from VenomCheats (slug=%s)", product.name, slug)
        return True
    except Exception as e:
        logger.warning("VenomCheats enrichment failed for '%s': %s", product.name, e)
        return False


def _backup_products_safe():
    try:
        from utils.kv_store import backup_products, backup_users
        ok_p = backup_products()
        ok_u = backup_users()
        return ok_p and ok_u
    except Exception as e:
        logger.error("Product backup to KV failed: %s", e)
        return False


_FALLBACK_TIERS = [
    ("1 Day", 1, 5.72),
    ("3 Days", 3, 14.74),
    ("7 Days", 7, 21.56),
    ("30 Days", 30, 41.40),
]

_PRIVATE_TIERS = [
    ("1 Month", 30, 49.99, True),
    ("12 Months", 365, 399.99, True),
]


def _get_vc_slug(product):
    if product.venomcheats_slug:
        return product.venomcheats_slug
    try:
        from utils.venomcheats import match_chairfbi_to_venom
        return match_chairfbi_to_venom(product.name)
    except Exception:
        return None


def _sync_product_tiers(product):
    if PricingTier.query.filter_by(product_id=product.id).first():
        return

    if product.visibility == "private":
        for label, days, price, sub in _PRIVATE_TIERS:
            db.session.add(PricingTier(
                product_id=product.id,
                label=label,
                duration_days=days,
                price_pence=int(round(price * 100)),
                billing_type="subscription" if sub else "one_time",
                is_subscription=bool(sub),
            ))
        db.session.commit()
        return

    existing_durations = {t.duration_days for t in PricingTier.query.filter_by(product_id=product.id).all()}

    for entry in _FALLBACK_TIERS:
        label = entry[0]
        days = entry[1]
        price = entry[2]
        bundle = entry[3] if len(entry) > 3 else 1

        if days in existing_durations:
            continue
        db.session.add(PricingTier(
            product_id=product.id,
            label=label,
            duration_days=days,
            price_pence=int(round(price * 100)),
            bundle_count=bundle,
        ))
        existing_durations.add(days)

    db.session.commit()


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/")
@admin_required
def dashboard():
    total_users = User.query.count()
    total_keys = Key.query.count()
    active_keys = Key.query.filter_by(is_active=True).count()
    total_orders = Order.query.count()
    completed_orders = Order.query.filter_by(status="completed").count()
    awaiting_keys = Order.query.filter_by(status="awaiting_keys").count()
    total_products = Product.query.count()
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    recent_keys = Key.query.order_by(Key.created_at.desc()).limit(5).all()

    revenue_pence = 0
    completed = Order.query.filter_by(status="completed").all()
    for o in completed:
        if o.tier:
            revenue_pence += o.tier.price_pence

    cf_balance = None
    cf_balance_raw = None
    cf_balance_error = None
    cf_config = get_chairfbi_config()
    if cf_config.get("api_token"):
        try:
            from utils.chairfbi import ChairFBI
            cf = ChairFBI(api_token=cf_config["api_token"], base_url=cf_config.get("api_base"))
            report = cf.get_balance_report()
            cf_balance = report["value"]
            cf_balance_raw = report["raw"]
        except Exception as e:
            err_str = str(e)
            if "502" in err_str or "Bad Gateway" in err_str:
                cf_balance_error = "ChairFBI temporarily unavailable — retrying shortly"
            else:
                cf_balance_error = err_str

    # Warn if the License API token is still the hardcoded default or unset —
    # key generation via the Project Infinity API will fail silently in that case.
    license_cfg = get_license_api_config()
    license_token_is_default = (
        not license_cfg["api_token"]
        or license_cfg["api_token"] == Config.LICENSE_API_TOKEN
    )
    products_using_license_api = Product.query.filter(Product.license_api_app_id.isnot(None)).count()

    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        total_keys=total_keys,
        active_keys=active_keys,
        total_orders=total_orders,
        completed_orders=completed_orders,
        awaiting_keys=awaiting_keys,
        total_products=total_products,
        revenue_pounds=revenue_pence / 100,
        recent_users=recent_users,
        recent_keys=recent_keys,
        cf_balance=cf_balance,
        cf_balance_raw=cf_balance_raw,
        cf_balance_error=cf_balance_error,
        license_token_is_default=license_token_is_default,
        license_api_url=license_cfg["api_url"],
        products_using_license_api=products_using_license_api,
    )


@admin_bp.route("/reviews")
@admin_required
def reviews():
    """Review moderation queue: newest first, pending ones highlighted."""
    all_reviews = (
        Review.query.order_by(Review.created_at.desc()).all()
    )
    counts = {
        "pending": sum(1 for r in all_reviews if r.status == "pending"),
        "approved": sum(1 for r in all_reviews if r.status == "approved"),
        "rejected": sum(1 for r in all_reviews if r.status == "rejected"),
    }
    return render_template("admin/reviews.html", reviews=all_reviews, counts=counts)

@admin_bp.route("/reviews/<int:review_id>/moderate", methods=["POST"])
@admin_required
def moderate_review(review_id):
    """Approve or reject a review. Approved reviews appear on the storefront."""
    review = db.session.get(Review, review_id)
    if not review:
        abort(404)
    action = request.form.get("action", "").strip()
    if action == "approve":
        review.status = "approved"
        review.approved_at = datetime.utcnow()
        flash("Review approved.", "success")
    elif action == "reject":
        review.status = "rejected"
        review.approved_at = None
        flash("Review rejected.", "success")
    elif action == "delete":
        db.session.delete(review)
        flash("Review deleted.", "success")
    else:
        flash("Unknown moderation action.", "error")
        return redirect(url_for("admin.reviews"))
    db.session.commit()
    return redirect(url_for("admin.reviews"))

@admin_bp.route("/reviews/<int:review_id>/delete", methods=["POST"])
@admin_required
def delete_review(review_id):
    review = db.session.get(Review, review_id)
    if not review:
        abort(404)
    db.session.delete(review)
    db.session.commit()
    flash("Review deleted.", "success")
    return redirect(url_for("admin.reviews"))

@admin_bp.route("/users")
@admin_required
def users():
    page = request.args.get("page", 1, type=int)
    users_list = User.query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=25, error_out=False
    )
    return render_template("admin/users.html", users=users_list)


@admin_bp.route("/users/<int:user_id>")
@admin_required
def user_detail(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    keys = Key.query.filter_by(user_id=user.id).order_by(Key.created_at.desc()).all()
    orders = Order.query.filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()
    return render_template("admin/user_detail.html", target_user=user, keys=keys, orders=orders)


@admin_bp.route("/users/<int:user_id>/impersonate", methods=["POST"])
@admin_required
def impersonate_user(user_id):
    """Log in as another user to see exactly what they see (My Keys, etc.).

    Stores the admin's id in the session so they can return with one click.
    Blocked for admin targets and disabled users for safety.
    """
    target = db.session.get(User, user_id)
    if not target:
        abort(404)
    if target.is_admin:
        flash("Can't log in as another admin.", "error")
        return redirect(url_for("admin.users"))
    if not target.is_active:
        flash("Can't log in as a disabled user — enable the account first.", "error")
        return redirect(url_for("admin.users"))

    from flask import session
    session["_impersonator_id"] = current_user.id
    admin_name = current_user.username
    login_user(target)
    logger.info("Admin %s (id=%s) is now impersonating user %s (id=%s)",
                admin_name, session.get("_impersonator_id"), target.username, target.id)
    flash(f"You are now viewing the site as {target.username}.", "info")
    return redirect(url_for("main.my_keys"))


@admin_bp.route("/stop-impersonating")
def stop_impersonating():
    """Return to the admin account after impersonating a user."""
    from flask import session
    impersonator_id = session.pop("_impersonator_id", None)
    if not impersonator_id:
        return redirect(url_for("main.index"))
    admin_user = db.session.get(User, impersonator_id)
    if not admin_user or not admin_user.is_admin:
        logout_user()
        return redirect(url_for("auth.login"))
    login_user(admin_user)
    logger.info("Returned to admin account %s", admin_user.username)
    flash("Returned to your admin account.", "info")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.is_admin:
        flash("Cannot disable an admin account.", "error")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    db.session.commit()
    flash(f"User {'activated' if user.is_active else 'deactivated'}.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.is_admin:
        flash("Cannot delete an admin account.", "error")
        return redirect(url_for("admin.users"))
    Key.query.filter_by(user_id=user.id).delete()
    Order.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash("User and all associated data deleted.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/keys")
@admin_required
def keys():
    page = request.args.get("page", 1, type=int)
    key_filter = request.args.get("filter", "")
    query = Key.query.order_by(Key.created_at.desc())
    if key_filter == "pool":
        query = query.filter(Key.user_id.is_(None))
    elif key_filter == "active":
        query = query.filter(Key.user_id.isnot(None), Key.is_active == True)
    elif key_filter == "expired":
        query = query.filter(Key.user_id.isnot(None), Key.is_active == False)
    keys_list = query.paginate(page=page, per_page=30, error_out=False)
    return render_template("admin/keys.html", keys=keys_list)


@admin_bp.route("/keys/<int:key_id>/toggle", methods=["POST"])
@admin_required
def toggle_key(key_id):
    key = db.session.get(Key, key_id)
    if not key:
        abort(404)
    key.is_active = not key.is_active
    db.session.commit()
    flash(f"Key {'activated' if key.is_active else 'revoked'}.", "success")
    return redirect(url_for("admin.keys"))


@admin_bp.route("/keys/<int:key_id>/delete", methods=["POST"])
@admin_required
def delete_key(key_id):
    key = db.session.get(Key, key_id)
    if not key:
        abort(404)
    db.session.delete(key)
    db.session.commit()
    flash("Key permanently deleted.", "success")
    return redirect(url_for("admin.keys"))


@admin_bp.route("/products")
@admin_required
def products():
    products_list = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin/products.html", products=products_list)


@admin_bp.route("/products/create", methods=["POST"])
@admin_required
def create_product():
    name = request.form.get("name", "").strip()
    slug = request.form.get("slug", "").strip()
    key_source = request.form.get("key_source", "chairfbi").strip()
    chairfbi_cheat_id = request.form.get("chairfbi_cheat_id", "").strip()
    license_api_app_id = request.form.get("license_api_app_id", "").strip() or None
    description = request.form.get("description", "").strip()
    image_url = request.form.get("image_url", "").strip()

    if not name:
        flash("Product name is required.", "error")
        return redirect(url_for("admin.products"))
    if not slug:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if Product.query.filter_by(slug=slug).first():
        flash(f"Slug '{slug}' already exists. Choose a different name.", "error")
        return redirect(url_for("admin.products"))
    if key_source not in ("pool", "chairfbi", "license"):
        flash("Key source must be pool, chairfbi, or license.", "error")
        return redirect(url_for("admin.products"))
    if key_source in ("pool", "license"):
        chairfbi_cheat_id = None
    visibility_val = request.form.get("visibility", "public").strip()
    if visibility_val not in ("private", "public"):
        visibility_val = "public"
    game = (request.form.get("game", "").strip() or None)

    product = Product(
        name=name,
        slug=slug,
        description=description or None,
        image_url=image_url or None,
        is_private=(visibility_val == "private"),
        key_source="chairfbi" if key_source in ("chairfbi", "license") else "pool",
        chairfbi_cheat_id=chairfbi_cheat_id or None,
        license_api_app_id=license_api_app_id,
        visibility=visibility_val,
        game=game,
    )
    db.session.add(product)
    db.session.commit()
    _backup_products_safe()
    try:
        from utils.kv_store import backup_everything
        backup_everything()
    except Exception:
        pass
    flash(f"Product '{name}' created.", "success")
    return redirect(url_for("admin.product_tiers", product_id=product.id))


@admin_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def delete_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)
    Order.query.filter(Order.tier.has(product_id=product.id)).delete(synchronize_session="fetch")
    Key.query.filter_by(product_id=product.id).delete(synchronize_session="fetch")
    PricingTier.query.filter_by(product_id=product.id).delete(synchronize_session="fetch")
    db.session.delete(product)
    db.session.commit()
    try:
        from utils.kv_store import backup_everything
        backup_everything()
    except Exception:
        pass
    flash(f"Product '{product.name}' and all associated keys/orders deleted.", "success")
    return redirect(url_for("admin.products"))


@admin_bp.route("/products/bulk-delete", methods=["POST"])
@admin_required
def bulk_delete_products():
    ids = request.form.getlist("product_ids")
    if not ids:
        flash("No products selected.", "error")
        return redirect(url_for("admin.products"))
    count = 0
    for pid in ids:
        product = db.session.get(Product, int(pid))
        if not product:
            continue
        Order.query.filter(Order.tier.has(product_id=product.id)).delete(synchronize_session="fetch")
        Key.query.filter_by(product_id=product.id).delete(synchronize_session="fetch")
        PricingTier.query.filter_by(product_id=product.id).delete(synchronize_session="fetch")
        db.session.delete(product)
        count += 1
    db.session.commit()
    _backup_products_safe()
    flash(f"{count} product(s) deleted.", "success")
    return redirect(url_for("admin.products"))


@admin_bp.route("/products/export")
@admin_required
def export_products():
    products = Product.query.order_by(Product.created_at.asc()).all()
    data = []
    for p in products:
        tiers = []
        for t in PricingTier.query.filter_by(product_id=p.id).order_by(PricingTier.duration_days).all():
            tiers.append({
                "label": t.label,
                "duration_days": t.duration_days,
                "price_pence": t.price_pence,
            })
        data.append({
            "name": p.name,
            "slug": p.slug,
            "description": p.description,
            "features_text": p.features_text,
            "buyer_notes": p.buyer_notes,
            "image_url": p.image_url,
            "key_source": p.key_source,
            "visibility": p.visibility,
            "chairfbi_cheat_id": p.chairfbi_cheat_id,
            "is_private": p.is_private,
            "tiers": tiers,
        })
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=beazt_products.json"}
    )


@admin_bp.route("/products/import", methods=["POST"])
@admin_required
def import_products():
    file = request.files.get("products_file")
    if not file or file.filename == "":
        flash("Please select a JSON file to import.", "error")
        return redirect(url_for("admin.products"))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        flash(f"Invalid JSON file: {e}", "error")
        return redirect(url_for("admin.products"))

    if not isinstance(data, list):
        flash("JSON must be an array of products.", "error")
        return redirect(url_for("admin.products"))

    created = 0
    updated = 0
    for entry in data:
        slug = entry.get("slug", "").strip()
        if not slug:
            continue

        product = Product.query.filter_by(slug=slug).first()
        if not product:
            product = Product(slug=slug)
            db.session.add(product)
            created += 1
        else:
            updated += 1

        product.name = entry.get("name", product.name or slug)
        product.description = entry.get("description") or None
        product.features_text = entry.get("features_text") or None
        product.buyer_notes = entry.get("buyer_notes") or None
        product.image_url = entry.get("image_url") or None
        product.key_source = entry.get("key_source", "chairfbi")
        product.visibility = entry.get("visibility", "public")
        product.chairfbi_cheat_id = entry.get("chairfbi_cheat_id") or None
        product.is_private = entry.get("is_private", True)
        db.session.flush()

        tiers_data = entry.get("tiers", [])
        PricingTier.query.filter_by(product_id=product.id).delete(synchronize_session="fetch")
        for t_entry in tiers_data:
            tier = PricingTier(
                product_id=product.id,
                label=t_entry.get("label", "Untitled"),
                duration_days=int(t_entry.get("duration_days", 1)),
                price_pence=int(t_entry.get("price_pence", 0)),
            )
            db.session.add(tier)

    db.session.commit()
    flash(f"Import complete: {created} created, {updated} updated.", "success")
    return redirect(url_for("admin.products"))


@admin_bp.route("/products/<int:product_id>/tiers", methods=["GET", "POST"])
@admin_required
def product_tiers(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)

    if request.method == "POST":
        cheat_id = request.form.get("chairfbi_cheat_id", "").strip()
        key_source_val = request.form.get("key_source", "").strip()
        license_app = request.form.get("license_api_app_id", "").strip()
        if license_app:
            key_source_val = "license"
        if key_source_val in ("pool", "chairfbi", "license"):
            product.key_source = "chairfbi" if key_source_val == "license" else key_source_val
            if key_source_val == "pool":
                product.chairfbi_cheat_id = None
                cheat_id = None
                product.license_api_app_id = None
            elif key_source_val == "license":
                product.chairfbi_cheat_id = None
                cheat_id = None
                if license_app:
                    product.license_api_app_id = license_app
            else:
                product.license_api_app_id = None
        product.chairfbi_cheat_id = cheat_id if cheat_id else None
        visibility_val = request.form.get("visibility", "").strip()
        if visibility_val in ("private", "public"):
            product.visibility = visibility_val
        status_val = request.form.get("status", "").strip()
        previous_status = product.status
        if status_val in ("undetected", "online", "offline", "maintenance"):
            product.status = status_val
        if "name" in request.form:
            new_name = request.form.get("name", "").strip()
            if new_name and new_name != product.name:
                product.name = new_name
        if "slug" in request.form:
            new_slug = request.form.get("slug", "").strip()
            if new_slug and new_slug != product.slug:
                if not Product.query.filter(Product.slug == new_slug, Product.id != product.id).first():
                    product.slug = new_slug
                else:
                    flash("Slug already taken. Keep the current one.", "error")
                    return redirect(url_for("admin.product_tiers", product_id=product.id))
        if "description" in request.form:
            product.description = request.form.get("description", "").strip() or None
        if "features_text" in request.form:
            product.features_text = request.form.get("features_text", "").strip() or None
        if "buyer_notes" in request.form:
            product.buyer_notes = request.form.get("buyer_notes", "").strip() or None
        if "game" in request.form:
            product.game = request.form.get("game", "").strip() or None
        # Featured pin: a select box, so it is always present in the form.
        product.is_featured = request.form.get("is_featured") == "1"

        image_file = request.files.get("image_file")
        if image_file and image_file.filename:
            ext = os.path.splitext(image_file.filename)[1].lower()
            if ext in (".png", ".jpg", ".jpeg", ".webp"):
                file_bytes = image_file.read()
                saved = False
                try:
                    upload_dir = os.path.join(current_app.root_path, "static", "images", "products", product.slug)
                    os.makedirs(upload_dir, exist_ok=True)
                    path = os.path.join(upload_dir, f"banner{ext}")
                    with open(path, "wb") as f:
                        f.write(file_bytes)
                    product.image_url = f"/static/images/products/{product.slug}/banner{ext}"
                    saved = True
                except OSError:
                    flash("Image upload failed — check directory permissions.", "error")
                if not saved:
                    pass  # already flashed error
            else:
                flash("Only PNG and JPEG files are accepted.", "error")
                return redirect(url_for("admin.product_tiers", product_id=product.id))
        elif "image_url" in request.form:
            image_url_val = request.form.get("image_url", "").strip()
            product.image_url = image_url_val if image_url_val else None

        loader_file = request.files.get("loader_file")
        if loader_file and loader_file.filename:
            ext = os.path.splitext(loader_file.filename)[1].lower()
            if ext in (".exe", ".zip", ".rar", ".7z"):
                file_bytes = loader_file.read()
                try:
                    upload_dir = os.path.join(current_app.root_path, "static", "loaders", product.slug)
                    os.makedirs(upload_dir, exist_ok=True)
                    path = os.path.join(upload_dir, f"loader{ext}")
                    with open(path, "wb") as f:
                        f.write(file_bytes)
                    product.loader_url = f"/static/loaders/{product.slug}/loader{ext}"
                except OSError:
                    flash("Loader upload failed — check directory permissions.", "error")
            else:
                flash("Only .exe, .zip, .rar, .7z files accepted for loaders.", "error")
        elif "loader_url" in request.form:
            # Loader URL text field — lets the admin paste an existing file path
            # (e.g. a previously uploaded loader) instead of re-uploading.
            loader_url_val = request.form.get("loader_url", "").strip()
            product.loader_url = loader_url_val if loader_url_val else None

        # Gallery image manager
        gallery = []
        if product.gallery_images:
            try:
                gallery = json.loads(product.gallery_images)
            except (json.JSONDecodeError, TypeError):
                pass

        delete_idx = request.form.get("delete_gallery_image", type=int)
        if delete_idx is not None and 0 <= delete_idx < len(gallery):
            gallery.pop(delete_idx)

        add_url = request.form.get("add_gallery_url", "").strip()
        if add_url:
            gallery.append(add_url)

        gallery_file = request.files.get("gallery_upload")
        if gallery_file and gallery_file.filename:
            ext = os.path.splitext(gallery_file.filename)[1].lower()
            if ext in (".png", ".jpg", ".jpeg", ".webp"):
                file_bytes = gallery_file.read()
                # Try local save first
                saved = False
                try:
                    upload_dir = os.path.join(current_app.root_path, "static", "images", "products", product.slug)
                    os.makedirs(upload_dir, exist_ok=True)
                    count = len([f for f in os.listdir(upload_dir) if f.startswith("gallery_")])
                    fname = f"gallery_{count}{ext}"
                    with open(os.path.join(upload_dir, fname), "wb") as f:
                        f.write(file_bytes)
                    gallery.append(f"/static/images/products/{product.slug}/{fname}")
                    saved = True
                except OSError:
                    flash("Gallery upload failed — check directory permissions.", "error")

        product.gallery_images = json.dumps(gallery) if gallery else None

        product.updated_at = datetime.utcnow()
        # VAL-ADM-005: an actual status change in the tiers editor appends a
        # StatusEvent row (status + note + timestamp) to the append-only
        # history that feeds the public status/freshness story. Re-saving
        # the same status records nothing, so the timeline stays honest.
        if product.status and product.status != previous_status:
            note = (request.form.get("status_note", "").strip()
                    or f"Status changed to {_ADMIN_STATUS_LABELS[product.status]}")
            db.session.add(StatusEvent(
                product_id=product.id,
                status=product.status,
                note=note,
            ))
        db.session.commit()
        try:
            from utils.kv_store import backup_everything
            backup_everything()
        except Exception:
            pass
        _backup_products_safe()
        product = db.session.get(Product, product_id)
        flash(f"Saved — key_source: {product.key_source}, app_id: {product.license_api_app_id or 'none'}", "success")
        return redirect(url_for("admin.product_tiers", product_id=product.id))

    gallery_imgs = []
    if product.gallery_images:
        try:
            gallery_imgs = json.loads(product.gallery_images)
        except (json.JSONDecodeError, TypeError):
            pass

    tiers = PricingTier.query.filter_by(product_id=product.id).order_by(PricingTier.duration_days).all()
    pool_count = Key.query.filter_by(product_id=product.id, user_id=None, is_active=False).count()
    return render_template("admin/product_tiers.html", product=product, tiers=tiers, gallery_imgs=gallery_imgs, pool_count=pool_count)


@admin_bp.route("/products/<int:product_id>/set-license-app", methods=["POST"])
@admin_required
def set_license_app(product_id):
    try:
        product = db.session.get(Product, product_id)
        if not product:
            return {"ok": False, "error": "Not found"}, 404
        data = request.get_json(force=True, silent=True) or {}
        app_id = (data.get("app_id") or "").strip()
        if app_id:
            product.license_api_app_id = app_id
            product.key_source = "chairfbi"
            product.updated_at = datetime.utcnow()
            db.session.commit()
            return {"ok": True, "app_id": app_id}
        else:
            product.license_api_app_id = None
            product.key_source = "chairfbi"
            product.updated_at = datetime.utcnow()
            db.session.commit()
            return {"ok": True, "app_id": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500


@admin_bp.route("/products/<int:product_id>/tiers/add", methods=["POST"])
@admin_required
def add_tier(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)
    label = request.form.get("label", "").strip()
    duration = request.form.get("duration_days", 0, type=int)
    price = request.form.get("price_pounds", 0, type=float)
    if not label or duration <= 0 or price <= 0:
        flash("All fields are required and must be positive.", "error")
        return redirect(url_for("admin.product_tiers", product_id=product.id))
    pence = int(round(price * 100))
    if pence <= 0:
        # Sub-penny inputs (e.g. 0.005) round down to a free tier — reject.
        flash("All fields are required and must be positive.", "error")
        return redirect(url_for("admin.product_tiers", product_id=product.id))
    billing_type_val = request.form.get("billing_type", "one_time", type=str)
    tier = PricingTier(
        product_id=product.id,
        label=label,
        duration_days=duration,
        price_pence=pence,
        billing_type=billing_type_val,
        is_subscription=(billing_type_val == "subscription"),
        ivno_subscription_link=request.form.get("ivno_subscription_link", "").strip() or None,
        bundle_count=request.form.get("bundle_count", 1, type=int),
    )
    db.session.add(tier)
    db.session.commit()
    flash(f"Tier '{label}' added.", "success")
    return redirect(url_for("admin.product_tiers", product_id=product.id))


@admin_bp.route("/tiers/<int:tier_id>/edit", methods=["POST"])
@admin_required
def edit_tier(tier_id):
    tier = db.session.get(PricingTier, tier_id)
    if not tier:
        abort(404)
    tier.label = request.form.get("label", tier.label).strip()
    tier.duration_days = request.form.get("duration_days", tier.duration_days, type=int)
    price = request.form.get("price_pounds", type=float)
    if price:
        pence = int(round(price * 100))
        if pence <= 0:
            # Sub-penny inputs (e.g. 0.005) round to 0 — never zero out a price.
            flash("Price must be a positive amount.", "error")
            return redirect(url_for("admin.product_tiers", product_id=tier.product_id))
        tier.price_pence = pence
    billing_type = request.form.get("billing_type")
    if billing_type in ("one_time", "subscription"):
        tier.billing_type = billing_type
        tier.is_subscription = (billing_type == "subscription")
    # Also handle is_subscription checkbox from tier row form
    is_sub = request.form.get("is_subscription")
    if is_sub is not None:
        tier.is_subscription = (is_sub == "1")
        tier.billing_type = "subscription" if tier.is_subscription else "one_time"
    sub_link = request.form.get("ivno_subscription_link", "").strip()
    if sub_link:
        tier.ivno_subscription_link = sub_link
    bundle_count = request.form.get("bundle_count", type=int)
    if bundle_count and bundle_count >= 1:
        tier.bundle_count = bundle_count
    db.session.commit()
    flash("Tier updated.", "success")
    return redirect(url_for("admin.product_tiers", product_id=tier.product_id))


@admin_bp.route("/tiers/<int:tier_id>/delete", methods=["POST"])
@admin_required
def delete_tier(tier_id):
    tier = db.session.get(PricingTier, tier_id)
    if not tier:
        abort(404)
    pid = tier.product_id
    # Get order IDs first, then clean up in correct FK order
    order_ids = [r.id for r in Order.query.filter_by(tier_id=tier_id).all()]
    if order_ids:
        Key.query.filter(Key.order_id.in_(order_ids)).update({"order_id": None, "is_active": False}, synchronize_session="fetch")
        Order.query.filter(Order.id.in_(order_ids)).delete(synchronize_session="fetch")
    Key.query.filter_by(tier_id=tier_id).update({"tier_id": None, "is_active": False}, synchronize_session="fetch")
    db.session.delete(tier)
    db.session.commit()
    flash("Tier deleted.", "success")
    return redirect(url_for("admin.product_tiers", product_id=pid))


@admin_bp.route("/orders")
@admin_required
def orders():
    status_filter = request.args.get("status", "")
    page = request.args.get("page", 1, type=int)
    query = Order.query.order_by(Order.created_at.desc())
    if status_filter:
        query = query.filter_by(status=status_filter)
    orders_list = query.paginate(page=page, per_page=30, error_out=False)

    pool_products = Product.query.filter_by(key_source="pool").all()
    pool_product_ids = [p.id for p in pool_products]
    pool_empty = {}
    for pid in pool_product_ids:
        count = Key.query.filter_by(product_id=pid, user_id=None, is_active=False).count()
        pool_empty[pid] = count

    return render_template(
        "admin/orders.html",
        orders=orders_list,
        status_filter=status_filter,
        pool_products=pool_products,
        pool_empty=pool_empty,
    )


@admin_bp.route("/orders/<int:order_id>/fulfill", methods=["POST"])
@admin_required
def fulfill_order(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)
    if order.status != "awaiting_keys":
        flash("This order is not awaiting keys.", "error")
        return redirect(url_for("admin.orders"))

    tier = order.tier
    product = tier.product if tier else None
    product_id = tier.product_id if tier else None
    tier_id = tier.id if tier else None
    duration_days = tier.duration_days if tier else 30
    expires_at = datetime.utcnow() + timedelta(days=duration_days)
    total_keys = (getattr(tier, "bundle_count", 1) or 1) * (getattr(order, "quantity", 1) or 1)
    is_sub = bool(getattr(tier, "is_subscription", False)) if tier else False

    # 1) Try License API (panel) first — especially for private products
    if product and product.license_api_app_id:
        from routes.checkout import try_license_api, _notify_buyer
        key_values, err = try_license_api(order, product, tier)
        if key_values:
            created = []
            for kv in key_values:
                key = Key(user_id=order.user_id, order_id=order.id, product_id=product_id,
                          tier_id=tier_id, key_value=kv, expires_at=expires_at, is_active=True,
                          is_subscription=is_sub)
                db.session.add(key)
                created.append(key)
            order.status = "completed"
            db.session.commit()
            _notify_buyer(order, product, tier, created)
            flash(f"Order #{order.id} fulfilled via License API ({len(key_values)} key(s)). Buyer emailed.", "success")
            return redirect(url_for("admin.orders"))
        flash(f"License API failed: {err}", "error")

    # 2) Fall back to pool key
    pool_key = (
        Key.query
        .filter_by(product_id=product_id, tier_id=tier_id, user_id=None, is_active=False)
        .order_by(Key.created_at.asc())
        .first()
    )
    if not pool_key:
        flash("No keys available — License API failed and no pool keys uploaded. Configure a License API App ID or upload pool keys.", "error")
        return redirect(url_for("admin.orders", status="awaiting_keys"))

    pool_key.user_id = order.user_id
    pool_key.order_id = order.id
    pool_key.tier_id = tier_id
    pool_key.expires_at = expires_at
    pool_key.assigned_at = datetime.utcnow()
    pool_key.is_active = True
    pool_key.is_subscription = is_sub
    order.status = "completed"
    db.session.commit()
    from routes.checkout import _notify_buyer
    _notify_buyer(order, product, tier, [pool_key])
    flash(f"Order #{order.id} fulfilled with key {pool_key.key_value[:20]}... Buyer emailed.", "success")
    return redirect(url_for("admin.orders"))


def _order_fulfillment_context(order):
    """Build the helper context (tier, product, expiry, available pool keys)
    used by the order detail page."""
    tier = order.tier
    product = tier.product if tier else None
    duration_days = tier.duration_days if tier else 30
    expires_at = datetime.utcnow() + timedelta(days=duration_days)
    product_id = tier.product_id if tier else None
    tier_id = tier.id if tier else None

    pool_keys = []
    if product_id and tier_id:
        pool_keys = (Key.query
                     .filter_by(product_id=product_id, tier_id=tier_id, user_id=None, is_active=False)
                     .order_by(Key.created_at.asc()).all())
    elif product_id:
        pool_keys = (Key.query
                     .filter_by(product_id=product_id, user_id=None, is_active=False)
                     .order_by(Key.created_at.asc()).all())

    existing_key = Key.query.filter_by(order_id=order.id).first()
    is_sub = bool(getattr(tier, "is_subscription", False)) if tier else False
    return {
        "tier": tier,
        "product": product,
        "duration_days": duration_days,
        "expires_at": expires_at,
        "product_id": product_id,
        "tier_id": tier_id,
        "is_sub": is_sub,
        "pool_keys": pool_keys,
        "existing_key": existing_key,
        "pool_count": len(pool_keys),
        "has_license_app": bool(product and product.license_api_app_id),
    }


@admin_bp.route("/orders/<int:order_id>")
@admin_required
def order_detail(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)
    ctx = _order_fulfillment_context(order)
    return render_template(
        "admin/order_detail.html",
        order=order,
        fctx=ctx,
    )


@admin_bp.route("/orders/<int:order_id>/assign-custom", methods=["POST"])
@admin_required
def assign_custom_key(order_id):
    """Admin pastes one or more key strings and assigns them to the order."""
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)

    raw = request.form.get("key_value", "").strip()
    if not raw:
        flash("Paste at least one key.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    ctx = _order_fulfillment_context(order)
    # One key per non-empty line, strip whitespace.
    key_values = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not key_values:
        flash("No valid key text found.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    if ctx["existing_key"] and order.status == "completed":
        flash("This order already has a key assigned. Delete the existing key first if you want to replace it.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    created = []
    for kv in key_values:
        key = Key(user_id=order.user_id, order_id=order.id,
                  product_id=ctx["product_id"], tier_id=ctx["tier_id"],
                  key_value=kv, expires_at=ctx["expires_at"], is_active=True,
                  is_subscription=ctx["is_sub"])
        db.session.add(key)
        created.append(key)
    order.status = "completed"
    db.session.commit()
    logger.info("Admin %s manually assigned %d custom key(s) to order %s",
                current_user.username, len(key_values), order.id)
    from routes.checkout import _notify_buyer
    _notify_buyer(order, ctx["product"], ctx["tier"], created)
    flash(f"Order #{order.id}: {len(key_values)} key(s) assigned manually. Buyer emailed.", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@admin_bp.route("/orders/<int:order_id>/assign-pool", methods=["POST"])
@admin_required
def assign_pool_key(order_id):
    """Admin picks a specific unassigned pool key to assign to the order."""
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)

    ctx = _order_fulfillment_context(order)
    if ctx["existing_key"] and order.status == "completed":
        flash("This order already has a key assigned. Delete the existing key first if you want to replace it.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    key_id = request.form.get("key_id", type=int)
    pool_key = db.session.get(Key, key_id) if key_id else None
    if not pool_key:
        flash("Select a valid pool key.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    if pool_key.user_id is not None or pool_key.is_active:
        flash("That pool key is already assigned. Pick another.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    pool_key.user_id = order.user_id
    pool_key.order_id = order.id
    pool_key.tier_id = ctx["tier_id"]
    pool_key.expires_at = ctx["expires_at"]
    pool_key.assigned_at = datetime.utcnow()
    pool_key.is_active = True
    pool_key.is_subscription = ctx["is_sub"]
    order.status = "completed"
    db.session.commit()
    logger.info("Admin %s assigned pool key %s to order %s",
                current_user.username, pool_key.id, order.id)
    from routes.checkout import _notify_buyer
    _notify_buyer(order, ctx["product"], ctx["tier"], [pool_key])
    flash(f"Order #{order.id}: pool key {pool_key.key_value[:20]}... assigned. Buyer emailed.", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@admin_bp.route("/orders/<int:order_id>/retry-license", methods=["POST"])
@admin_required
def retry_license(order_id):
    """Re-run the Project Infinity License API key generation for an order."""
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)

    ctx = _order_fulfillment_context(order)
    product = ctx["product"]
    tier = ctx["tier"]

    if not (product and product.license_api_app_id):
        flash("Cannot retry: this product has no License App ID configured. Set one in the product's Key Source settings.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    if ctx["existing_key"] and order.status == "completed":
        flash("This order already has a key assigned. Delete the existing key first if you want to replace it.", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    from routes.checkout import try_license_api, _notify_buyer
    key_values, err = try_license_api(order, product, tier)
    if key_values:
        created = []
        for kv in key_values:
            key = Key(user_id=order.user_id, order_id=order.id,
                      product_id=ctx["product_id"], tier_id=ctx["tier_id"],
                      key_value=kv, expires_at=ctx["expires_at"], is_active=True,
                      is_subscription=ctx["is_sub"])
            db.session.add(key)
            created.append(key)
        order.status = "completed"
        db.session.commit()
        logger.info("Admin %s retried License API for order %s — %d key(s) generated",
                    current_user.username, order.id, len(key_values))
        _notify_buyer(order, product, tier, created)
        flash(f"Order #{order.id}: {len(key_values)} key(s) generated via Project Infinity API. Buyer emailed.", "success")
    else:
        flash(f"License API retry failed: {err}", "error")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@admin_bp.route("/products/<int:product_id>/test-license-api", methods=["POST"])
@admin_required
def test_license_api(product_id):
    """Diagnostic: probe the Project Infinity API for a product.

    Returns JSON describing: whether an app id is configured, the working auth
    scheme (bearer vs raw, with status + body for each), the available apps,
    and — if an app id is set — a dry-run of listing licenses for that app.
    """
    product = db.session.get(Product, product_id)
    if not product:
        return {"ok": False, "error": "Product not found"}, 404

    from utils.license_api import LicenseAPI
    from config import get_license_api_config
    lcfg = get_license_api_config()
    token = lcfg["api_token"]
    base = lcfg["api_url"]
    configured_scheme = lcfg["auth_scheme"]
    app_id = product.license_api_app_id

    report = {
        "ok": True,
        "product": product.name,
        "app_id_configured": bool(app_id),
        "app_id": app_id,
        "token_set": bool(token),
        "token_preview": (token[:10] + "...") if token else "",
        "base_url": base,
        "configured_scheme": configured_scheme,
    }

    if not token:
        report["auth"] = {"error": "LICENSE_API_TOKEN is not set."}
        return report

    api = LicenseAPI(api_token=token, base_url=base)
    try:
        report["auth_diagnosis"] = api.diagnose()
    except Exception as exc:  # noqa: BLE001 - diagnostics
        report["auth_diagnosis"] = {"error": str(exc)[:500]}

    # If an app id is configured, try listing its licenses (read-only) to
    # confirm the app is reachable with the recommended scheme.
    if app_id:
        recommended = (report.get("auth_diagnosis") or {}).get("recommended") or configured_scheme
        api = LicenseAPI(api_token=token, base_url=base, auth_scheme=recommended)
        try:
            licenses = api.get_licenses(app_id)
            report["licenses"] = {
                "status": api.last_response.status_code if api.last_response else None,
                "count": len(licenses) if isinstance(licenses, list) else None,
                "preview": str(licenses)[:800],
            }
        except Exception as exc:  # noqa: BLE001 - diagnostics
            report["licenses"] = {
                "status": api.last_response.status_code if api.last_response else None,
                "error": str(exc)[:500],
                "body": (api.last_response.text[:800] if api.last_response is not None else ""),
            }
    return report


@admin_bp.route("/products/<int:product_id>/keys", methods=["GET", "POST"])
@admin_required
def product_keys(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)
    tier_id = request.args.get("tier_id", type=int)

    if request.method == "POST":
        action = request.form.get("action", "add")
        if action == "add":
            raw_keys = request.form.get("keys_text", "").strip()
            sel_tier_id = request.form.get("tier_id", type=int)
            if not raw_keys:
                flash("Paste at least one key.", "error")
                return redirect(url_for("admin.product_keys", product_id=product.id, tier_id=sel_tier_id))
            tier = db.session.get(PricingTier, sel_tier_id) if sel_tier_id else None
            if sel_tier_id and not tier:
                flash("Invalid tier selected.", "error")
                return redirect(url_for("admin.product_keys", product_id=product.id))
            lines = [line.strip() for line in raw_keys.splitlines() if line.strip()]
            added = 0
            skipped = 0
            for line in lines:
                existing = Key.query.filter_by(key_value=line).first()
                if existing:
                    skipped += 1
                    continue
                key = Key(
                    user_id=None,
                    product_id=product.id,
                    tier_id=tier.id if tier else None,
                    key_value=line,
                    is_active=False,
                )
                db.session.add(key)
                added += 1
            db.session.commit()
            flash(f"{added} key(s) added to pool. {skipped} duplicate(s) skipped.", "success")
            return redirect(url_for("admin.product_keys", product_id=product.id, tier_id=sel_tier_id))

        elif action == "delete_pool":
            key_ids = request.form.getlist("key_ids")
            if key_ids:
                Key.query.filter(Key.id.in_([int(k) for k in key_ids]), Key.user_id.is_(None)).delete(synchronize_session="fetch")
                db.session.commit()
                flash(f"{len(key_ids)} pool key(s) deleted.", "success")
            return redirect(url_for("admin.product_keys", product_id=product.id, tier_id=tier_id))

    tiers = PricingTier.query.filter_by(product_id=product.id).order_by(PricingTier.duration_days).all()
    pool_query = Key.query.filter_by(product_id=product.id).filter(Key.user_id.is_(None)).order_by(Key.created_at.desc())
    if tier_id:
        pool_query = pool_query.filter_by(tier_id=tier_id)
    pool_keys = pool_query.all()

    pool_stats = {}
    for t in tiers:
        total = Key.query.filter_by(product_id=product.id, tier_id=t.id).count()
        unassigned = Key.query.filter_by(product_id=product.id, tier_id=t.id).filter(Key.user_id.is_(None)).count()
        assigned = Key.query.filter_by(product_id=product.id, tier_id=t.id).filter(Key.user_id.isnot(None)).count()
        pool_stats[t.id] = {"total": total, "available": unassigned, "assigned": assigned}

    return render_template(
        "admin/product_keys.html",
        product=product,
        tiers=tiers,
        pool_keys=pool_keys,
        selected_tier_id=tier_id,
        pool_stats=pool_stats,
    )


@admin_bp.route("/settings/chairfbi-test", methods=["POST"])
@admin_required
def test_chairfbi():
    from utils.chairfbi import ChairFBI

    token = request.form.get("chairfbi_api_token", "").strip()
    base_url = request.form.get("chairfbi_api_base", "").strip()

    if not token:
        flash("Please enter an API token first.", "error")
        return redirect(url_for("admin.settings"))

    cf = ChairFBI(api_token=token, base_url=base_url or None)
    success, result = cf.test_connection()

    if success:
        balance = ChairFBI.parse_balance(result)
        if balance is not None:
            flash(f"ChairFBI connection successful. Balance: €{balance} (raw: {ChairFBI._find_raw(result)}).", "success")
        else:
            flash("ChairFBI connection successful.", "success")
    else:
        flash(f"ChairFBI connection failed: {result}", "error")

    return redirect(url_for("admin.settings"))


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        fields = {
            "site_url": "Site URL",
            "chairfbi_api_token": "ChairFBI API Token",
            "chairfbi_api_base": "ChairFBI API Base URL",
            "ivno_api_key": "Ivno API Key",
            "ivno_api_secret": "Ivno API Secret",
            "payfast_merchant_id": "PayFast Merchant ID",
            "payfast_merchant_key": "PayFast Merchant Key",
            "payfast_passphrase": "PayFast Passphrase",
            "payfast_item_name": "PayFast Checkout Label",
            "loader_token": "Loader Token",
            "loader_url": "Loader Download URL",
            "loader_public_url": "Public Loader Download URL",
            "loader_private_url": "Private Loader Download URL",
            "discord_public_url": "Public Discord URL",
            "discord_private_url": "Private Discord URL",
            "license_api_token": "License API Token",
            "license_api_url": "License API URL",
            "license_api_auth_scheme": "License API Auth Scheme",
            "smtp_host": "SMTP Host",
            "smtp_port": "SMTP Port",
            "smtp_user": "SMTP Username",
            "smtp_pass": "SMTP Password",
            "smtp_use_tls": "SMTP Use TLS",
            "smtp_from_email": "From Email",
            "smtp_from_name": "From Name",
        }
        for key, label in fields.items():
            val = request.form.get(key, "").strip()
            if val:
                Setting.set(key, val)
                flash(f"{label} saved.", "success")
            else:
                row = db.session.execute(db.select(Setting).filter_by(key=key)).scalar_one_or_none()
                if row:
                    db.session.delete(row)
                    db.session.commit()
                    flash(f"{label} cleared.", "info")

        # Handle loader file uploads
        for field_name, setting_key, label in [
            ("loader_public_file", "loader_public_url", "Public Loader"),
            ("loader_private_file", "loader_private_url", "Private Loader"),
        ]:
            loader_file = request.files.get(field_name)
            if loader_file and loader_file.filename:
                ext = os.path.splitext(loader_file.filename)[1].lower()
                if ext in (".exe", ".zip", ".rar", ".7z"):
                    try:
                        upload_dir = os.path.join(current_app.root_path, "static", "loaders")
                        os.makedirs(upload_dir, exist_ok=True)
                        fname = {"loader_public_file": "loader-public", "loader_private_file": "loader-private"}[field_name] + ext
                        path = os.path.join(upload_dir, fname)
                        with open(path, "wb") as f:
                            f.write(loader_file.read())
                        url = f"/static/loaders/{fname}"
                        Setting.set(setting_key, url)
                        flash(f"{label} uploaded.", "success")
                    except OSError:
                        flash(f"{label} upload failed.", "error")

        try:
            from utils.kv_store import backup_everything
            backup_everything()
        except Exception:
            pass
        return redirect(url_for("admin.settings"))

    cf_cfg = get_chairfbi_config()
    loader_cfg = get_loader_config()
    discord_cfg = get_discord_config()
    ivno_cfg = get_ivno_config()
    license_cfg = get_license_api_config()
    mailer_cfg = get_mailer_config()
    return render_template("admin/settings.html",
        site_url=Config.SITE_URL,
        chairfbi_api_token=cf_cfg["api_token"],
        chairfbi_api_base=cf_cfg["api_base"],
        ivno_api_key=ivno_cfg["api_key"],
        ivno_api_secret=ivno_cfg["api_secret"],
        payfast_merchant_id=Setting.get("payfast_merchant_id") or "",
        payfast_merchant_key=Setting.get("payfast_merchant_key") or "",
        payfast_passphrase=Setting.get("payfast_passphrase") or "",
        payfast_item_name=Setting.get("payfast_item_name") or "",
        loader_token=loader_cfg["loader_token"],
        loader_url=loader_cfg.get("loader_url", ""),
        loader_public_url=loader_cfg.get("loader_public_url", ""),
        loader_private_url=loader_cfg.get("loader_private_url", ""),
        discord_public_url=discord_cfg.get("public_url", ""),
        discord_private_url=discord_cfg.get("private_url", ""),
        license_api_token=license_cfg["api_token"],
        license_api_url=license_cfg["api_url"],
        license_api_auth_scheme=license_cfg["auth_scheme"],
        smtp_host=mailer_cfg["smtp_host"],
        smtp_port=mailer_cfg["smtp_port"],
        smtp_user=mailer_cfg["smtp_user"],
        smtp_pass=mailer_cfg["smtp_pass"],
        smtp_use_tls=mailer_cfg["use_tls"],
        smtp_from_email=mailer_cfg["from_email"],
        smtp_from_name=mailer_cfg["from_name"])


@admin_bp.route("/chairfbi")
@admin_required
def chairfbi_dashboard():
    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.com")

    balance = None
    cf_balance = None
    cf_balance_raw = None
    cheats = []
    recent_cf_keys = []
    chairfbi_error = None
    balance_error = None

    if not api_token:
        chairfbi_error = "ChairFBI API token not configured. Add it in Settings."
    else:
        try:
            from utils.chairfbi import ChairFBI
            cf = ChairFBI(api_token=api_token, base_url=api_base)

            try:
                report = cf.get_balance_report()
                cf_balance = report["value"]
                cf_balance_raw = report["raw"]
            except Exception as e:
                err_str = str(e)
                if "502" in err_str or "Bad Gateway" in err_str:
                    balance_error = "ChairFBI temporarily unavailable — retrying shortly"
                else:
                    balance_error = err_str

            try:
                cheats_data = cf.get_cheats()
                cheats = cheats_data if isinstance(cheats_data, list) else []
            except Exception:
                pass

            try:
                keys_data = cf.list_keys(per_page=20)
                recent_cf_keys = keys_data.get("data", []) if isinstance(keys_data, dict) else keys_data if isinstance(keys_data, list) else []
            except Exception:
                pass
        except Exception as e:
            chairfbi_error = str(e)

    products = Product.query.order_by(Product.name).all()
    local_cf_keys = Key.query.filter(Key.chairfbi_key_id.isnot(None)).order_by(Key.created_at.desc()).limit(30).all()

    kv_configured = bool(os.environ.get("KV_URL") or os.environ.get("KV_REST_API_URL") or os.environ.get("REDIS_URL"))

    vc_synced_count = Product.query.filter(Product.venomcheats_slug.isnot(None)).count()
    vc_rating = Setting.query.filter_by(key="venomcheats_rating").first()
    vc_rating_data = None
    if vc_rating and vc_rating.value:
        try:
            vc_rating_data = json.loads(vc_rating.value)
        except json.JSONDecodeError:
            pass

    try:
        from utils.sync import get_last_sync_time
        vc_last_sync = get_last_sync_time()
    except Exception:
        vc_last_sync = None

    return render_template(
        "admin/chairfbi.html",
        balance=cf_balance,
        balance_raw=cf_balance_raw,
        balance_error=balance_error,
        cheats=cheats,
        recent_cf_keys=recent_cf_keys,
        chairfbi_error=chairfbi_error,
        products=products,
        local_cf_keys=local_cf_keys,
        vc_synced_count=vc_synced_count,
        vc_rating=vc_rating_data,
        vc_last_sync=vc_last_sync,
        kv_configured=kv_configured,
        is_vercel=os.environ.get("VERCEL") == "1",
    )


@admin_bp.route("/chairfbi/import-one", methods=["POST"])
@admin_required
def chairfbi_import_one():
    cheat_id = request.form.get("cheat_id", "").strip()
    cheat_name = request.form.get("cheat_name", "").strip()
    if not cheat_id or not cheat_name:
        flash("Missing cheat ID or name.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    slug = re.sub(r"[^a-z0-9]+", "-", cheat_name.lower()).strip("-")
    if not slug:
        slug = f"cf-cheat-{cheat_id}"

    existing = Product.query.filter_by(slug=slug).first()
    if existing:
        if not existing.chairfbi_cheat_id or existing.chairfbi_cheat_id != cheat_id:
            existing.chairfbi_cheat_id = cheat_id
            existing.key_source = "chairfbi"
            db.session.commit()
            flash(f"'{cheat_name}' was already imported — ChairFBI cheat ID updated.", "info")
        else:
            flash(f"'{cheat_name}' already exists as a product.", "info")

        _enrich_product_from_venomcheats(existing)
        return redirect(url_for("admin.product_tiers", product_id=existing.id))

    product = Product(
        name=cheat_name,
        slug=slug,
        key_source="chairfbi",
        chairfbi_cheat_id=cheat_id,
        is_private=False,
    )
    db.session.add(product)
    db.session.commit()
    try:
        from utils.kv_store import backup_everything
        backup_everything()
    except Exception:
        pass
    _backup_products_safe()
    _sync_product_tiers(product)

    enriched = _enrich_product_from_venomcheats(product)
    if enriched:
        flash(f"'{cheat_name}' imported + enriched from VenomCheats. Add pricing tiers to activate.", "success")
    else:
        flash(f"'{cheat_name}' imported. Add pricing tiers to activate.", "success")
    return redirect(url_for("admin.product_tiers", product_id=product.id))


@admin_bp.route("/chairfbi/import-all", methods=["POST"])
@admin_required
def chairfbi_import_all():
    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.com")

    if not api_token:
        flash("ChairFBI API token not configured.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        cheats_data = cf.get_cheats()
        cheats = cheats_data if isinstance(cheats_data, list) else []

        online_only = request.form.get("online_only") == "1"
        if online_only:
            cheats = [c for c in cheats if c.get("active")]

        created = 0
        skipped = 0
        enriched = 0
        for cheat in cheats:
            cheat_id = str(cheat.get("id", ""))
            cheat_name = cheat.get("name", "Unknown Cheat").strip()
            if not cheat_name:
                continue

            slug = re.sub(r"[^a-z0-9]+", "-", cheat_name.lower()).strip("-")
            if not slug:
                slug = f"cf-cheat-{cheat_id}"

            existing = Product.query.filter_by(slug=slug).first()
            if existing:
                if not existing.chairfbi_cheat_id or existing.chairfbi_cheat_id != cheat_id:
                    existing.chairfbi_cheat_id = cheat_id
                    existing.key_source = "chairfbi"
                if _enrich_product_from_venomcheats(existing):
                    enriched += 1
                skipped += 1
                continue

            product = Product(
                name=cheat_name,
                slug=slug,
                description=None,
                key_source="chairfbi",
                chairfbi_cheat_id=cheat_id,
                is_private=False,
            )
            db.session.add(product)
            created += 1

        db.session.commit()
        _backup_products_safe()
        try:
            from utils.kv_store import backup_everything
            backup_everything()
        except Exception:
            pass

        vc_prefetched = None
        try:
            from utils.venomcheats import get_all_products
            vc_prefetched = get_all_products()
        except Exception:
            pass

        for product in Product.query.order_by(Product.id).all():
            _sync_product_tiers(product)
            if vc_prefetched:
                if _enrich_product_from_venomcheats(product, vc_products=vc_prefetched):
                    enriched += 1

        msg = f"Imported {created} new cheat(s) from ChairFBI. {skipped} already exist."
        if enriched:
            msg += f" {enriched} enriched from VenomCheats."
        flash(msg, "success")
    except Exception as e:
        flash(f"ChairFBI import failed: {e}", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))


@admin_bp.route("/chairfbi/revoke/<int:key_id>", methods=["POST"])
@admin_required
def chairfbi_revoke(key_id):
    key = db.session.get(Key, key_id)
    if not key or not key.chairfbi_key_id:
        flash("No ChairFBI key ID found for this key.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.com")

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        cf.revoke_key(key.chairfbi_key_id)
        key.is_active = False
        db.session.commit()
        flash("ChairFBI key revoked successfully.", "success")
    except Exception as e:
        flash(f"ChairFBI revoke failed: {e}", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))


@admin_bp.route("/chairfbi/delete/<int:key_id>", methods=["POST"])
@admin_required
def chairfbi_delete(key_id):
    """Delete an UNUSED key on ChairFBI (refunds balance).

    Started keys cannot be deleted directly — ChairFBI requires an approval
    request via POST /api/keys-delete-request, reviewed on their panel.
    """
    from utils.chairfbi import ChairFBIRateLimitError

    key = db.session.get(Key, key_id)
    if not key or not key.chairfbi_key_id:
        flash("No ChairFBI key ID found for this key.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.com")

    if not api_token:
        flash("ChairFBI API token not configured.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        result = cf.delete_keys([key.chairfbi_key_id])
        key.is_active = False
        db.session.commit()
        refunded = result.get("totalRefunded")
        msg = "ChairFBI key deleted successfully."
        if refunded:
            msg += f" Balance refunded: {refunded}"
        flash(msg, "success")
    except ChairFBIRateLimitError as e:
        flash(f"ChairFBI rate limit hit — try again in ~{e.available_in or 45}s: {e}", "error")
    except Exception as e:
        # 400 typically means the key was started: ChairFBI only allows
        # started keys to go through the admin-approval deletion flow.
        flash(f"ChairFBI key delete failed: {e}. If the key has been started, it must be deleted via the ChairFBI panel approval flow.", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))


@admin_bp.route("/chairfbi/hwid-reset/<int:key_id>", methods=["POST"])
@admin_required
def chairfbi_hwid_reset(key_id):
    key = db.session.get(Key, key_id)
    if not key or not key.chairfbi_key_id:
        flash("No ChairFBI key ID found for this key.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.com")

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        resp = cf.update_keys(keys=[key.chairfbi_key_id], hwid=True)
        if resp.get("errors", 0) == 0:
            flash("HWID reset successful.", "success")
        else:
            flash("HWID reset failed.", "error")
    except Exception as e:
        flash(f"HWID reset failed: {e}", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))


@admin_bp.route("/chairfbi/vouche/<int:key_id>", methods=["POST"])
@admin_required
def chairfbi_vouche(key_id):
    key = db.session.get(Key, key_id)
    if not key or not key.chairfbi_key_id:
        flash("No ChairFBI key ID found for this key.", "error")
        return redirect(url_for("admin.chairfbi_dashboard"))

    cfg = get_chairfbi_config()
    api_token = cfg.get("api_token", "")
    api_base = cfg.get("api_base", "https://access.chairfbi.com")

    try:
        from utils.chairfbi import ChairFBI
        cf = ChairFBI(api_token=api_token, base_url=api_base)
        resp = cf.update_keys(keys=[key.chairfbi_key_id], vouche=True)
        if resp.get("errors", 0) == 0:
            flash("Vouche (6 hours) added successfully.", "success")
        else:
            flash("Vouche failed.", "error")
    except Exception as e:
        flash(f"Vouche failed: {e}", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))


@admin_bp.route("/chairfbi/sync-venomcheats", methods=["POST"])
@admin_required
def chairfbi_sync_venomcheats():
    try:
        from utils.venomcheats import sync_all, get_rating

        static_dir = os.path.join(current_app.root_path, "static")
        vc_data = sync_all(static_dir=static_dir)

        if not vc_data:
            flash("No data received from VenomCheats.", "error")
            return redirect(url_for("admin.chairfbi_dashboard"))

        products = Product.query.all()
        updated = 0
        for product in products:
            if _enrich_product_from_venomcheats(product, vc_products=vc_data):
                _sync_product_tiers(product)
                updated += 1

        rating = get_rating()
        if rating:
            existing = Setting.query.filter_by(key="venomcheats_rating").first()
            if existing:
                existing.value = json.dumps(rating)
            else:
                db.session.add(Setting(key="venomcheats_rating", value=json.dumps(rating)))

        db.session.commit()
        _backup_products_safe()
        flash(f"Updated {updated} product(s) from VenomCheats.", "success")
    except Exception as e:
        flash(f"VenomCheats sync failed: {e}", "error")

    return redirect(url_for("admin.chairfbi_dashboard"))
