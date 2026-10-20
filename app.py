import gzip
import hmac
import os
import secrets
from flask import Flask, jsonify, render_template, request, session
from config import Config
from models import db, User, seed_products
from flask_login import LoginManager

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "info"

_basedir = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    static_folder=os.path.join(_basedir, "static"),
    static_url_path="/static",
)
app.config.from_object(Config)
# --- Session hardening (VAL-SEC-003) ---------------------------------------
app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")

# --- CSRF protection (VAL-SEC-004) -----------------------------------------
# Lightweight, dependency-free implementation (chosen over Flask-WTF/CSRFProtect
# to avoid adding a dependency for one feature): a per-session random token
# validated with a constant-time comparison on every state-changing request.
# Server-to-server payment webhooks are exempt (they carry no browser session):
#   /checkout/ivno-webhook, /checkout/payfast-notify, /webhooks/sellix
_CSRF_EXEMPT_PATHS = (
    "/checkout/ivno-webhook",
    "/checkout/payfast-notify",
    "/webhooks/sellix",
)


def _get_csrf_token():
    """Lazily create and return this session's CSRF token (Jinja global)."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


app.jinja_env.globals["csrf_token"] = _get_csrf_token


@app.before_request
def csrf_protect():
    """Reject state-changing requests without a valid CSRF token (400).

    Tokens are accepted from the form field (browser forms), the X-CSRF-Token
    header (fetch/AJAX), or a JSON body field. Webhook paths are exempt.
    """
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None

    path = (request.path or "").rstrip("/")
    if path in _CSRF_EXEMPT_PATHS:
        return None

    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not supplied and request.is_json:
        supplied = (request.get_json(silent=True) or {}).get("csrf_token")

    stored = session.get("_csrf_token")
    if not stored or not supplied or not hmac.compare_digest(
        str(stored), str(supplied)
    ):
        return jsonify({"error": "CSRF token missing or invalid"}), 400
    return None

# ---------------------------------------------------------------------------




# --- Response compression (VAL-PERF-001) ------------------------------------
# The render-blocking CSS bundle dominates the critical path on slow networks;
# gzip cuts ~170KB of CSS to ~30KB. Flask servers do not compress by default,
# so compress text responses when the client advertises support (dependency-
# free: stdlib gzip + an after_request hook).
_GZIP_CONTENT_TYPES = (
    "text/html",
    "text/css",
    "application/javascript",
    "text/javascript",
    "application/json",
    "image/svg+xml",
    "text/plain",
)
_GZIP_MIN_SIZE = 860  # bytes; smaller responses gain nothing from gzip

@app.after_request
def compress_response(response):
    if response.status_code != 200:
        return response
    content_type = (response.content_type or "").split(";")[0].strip()
    if content_type not in _GZIP_CONTENT_TYPES:
        return response
    accept = request.headers.get("Accept-Encoding", "")
    if "gzip" not in accept.lower():
        return response
    if response.headers.get("Content-Encoding"):
        return response
    if response.direct_passthrough:
        # Static-file responses (send_file) stream from disk; buffer them so
        # the body can be read and re-encoded.
        response.direct_passthrough = False
    data = response.get_data()
    if len(data) < _GZIP_MIN_SIZE:
        return response
    compressed = gzip.compress(data, compresslevel=5)
    if len(compressed) >= len(data):
        return response
    response.set_data(compressed)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(compressed))
    # Append (do not overwrite) Accept-Encoding: authed responses already
    # carry Vary: Cookie (session handling), and clobbering it would let
    # shared caches serve one user's compressed page to another.
    vary = [v.strip() for v in response.headers.get("Vary", "").split(",") if v.strip()]
    if "Accept-Encoding" not in vary:
        vary.append("Accept-Encoding")
    response.headers["Vary"] = ", ".join(vary)
    response.headers.pop("ETag", None)  # representation changed
    return response

@app.route("/ping")
def ping():
    return "ok"


db.init_app(app)
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


try:
    from routes.main import main_bp
except Exception:
    main_bp = None
try:
    from routes.auth import auth_bp
except Exception:
    auth_bp = None
try:
    from routes.checkout import checkout_bp
except Exception:
    checkout_bp = None
try:
    from routes.admin import admin_bp
except Exception:
    admin_bp = None

if main_bp:
    app.register_blueprint(main_bp)
if auth_bp:
    app.register_blueprint(auth_bp, url_prefix="/auth")
if checkout_bp:
    app.register_blueprint(checkout_bp, url_prefix="/checkout")
if admin_bp:
    app.register_blueprint(admin_bp, url_prefix="/admin")


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.route("/webhooks/sellix", methods=["POST"])
def legacy_webhook():
    return jsonify({"status": "deprecated", "error": "Sellix is no longer supported"}), 410


@app.context_processor
def inject_discord():
    try:
        from config import get_discord_config
        cfg = get_discord_config()
        return {"discord_public_url": cfg["public_url"]}
    except Exception:
        return {"discord_public_url": "https://discord.gg/X8yQuMYsxp"}


@app.context_processor
def inject_honest_stats():
    # Exposed as a callable so only templates that show stats run the queries.
    from utils.catalogue import format_date, honest_stats
    return {"honest_stats": honest_stats, "format_date": format_date}


# NOTE (m2-product-page): the former inject_verified_date context processor
# was removed. It stamped "Updated <today>" with the render-time date, which
# contradicted the honesty rule — freshness labels must come from DB data
# (products.last_verified_at or the latest StatusEvent) via
# utils/catalogue.freshness(), exactly like the catalogue cards.


with app.app_context():
    db.create_all()

    import sqlite3
    try:
        _engine = db.engine
        _conn = _engine.raw_connection()
        _cursor = _conn.cursor()

        # Ensure products table has chairfbi_cheat_id
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "chairfbi_cheat_id" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN chairfbi_cheat_id VARCHAR(64)")
            _conn.commit()

        # Ensure products table has license_api_app_id
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "license_api_app_id" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN license_api_app_id VARCHAR(64)")
            _conn.commit()

        # Ensure products table has key_source
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "key_source" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN key_source VARCHAR(16) DEFAULT 'chairfbi'")
            _conn.commit()
            _cursor.execute("UPDATE products SET key_source='pool' WHERE chairfbi_cheat_id IS NULL OR chairfbi_cheat_id=''")
            _conn.commit()

        # Ensure products table has last_verified_at
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "last_verified_at" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN last_verified_at DATETIME")
            _conn.commit()

        # Ensure products table has features_text
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "features_text" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN features_text TEXT")
            _conn.commit()

        # Ensure products table has buyer_notes
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "buyer_notes" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN buyer_notes TEXT")
            _conn.commit()

        # Ensure products table has visibility
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "visibility" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN visibility VARCHAR(16) DEFAULT 'public'")
            _conn.commit()
            _cursor.execute("UPDATE products SET visibility='private' WHERE key_source='pool'")
            _conn.commit()

        # Ensure pricing_tiers has billing_type, ivno_subscription_link
        _cursor.execute("PRAGMA table_info(pricing_tiers)")
        _tier_cols = [r[1] for r in _cursor.fetchall()]
        if "billing_type" not in _tier_cols:
            _cursor.execute("ALTER TABLE pricing_tiers ADD COLUMN billing_type VARCHAR(16) DEFAULT 'one_time'")
            _conn.commit()
        if "ivno_subscription_link" not in _tier_cols:
            _cursor.execute("ALTER TABLE pricing_tiers ADD COLUMN ivno_subscription_link VARCHAR(512)")
            _conn.commit()
        if "bundle_count" not in _tier_cols:
            _cursor.execute("ALTER TABLE pricing_tiers ADD COLUMN bundle_count INTEGER DEFAULT 1")
            _conn.commit()

        # Ensure products table has venomcheats_slug
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "venomcheats_slug" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN venomcheats_slug VARCHAR(64)")
            _conn.commit()

        # Ensure products table has venomcheats_data
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "venomcheats_data" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN venomcheats_data TEXT")
            _conn.commit()

        # Ensure products table has last_synced_at
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "last_synced_at" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN last_synced_at DATETIME")
            _conn.commit()

        # Ensure products table has gallery_images
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "gallery_images" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN gallery_images TEXT")
            _conn.commit()

        # Ensure products table has updated_at
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "updated_at" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN updated_at DATETIME")
            _conn.commit()

        # Ensure products table has status
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "status" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN status VARCHAR(16) DEFAULT 'undetected'")
            _conn.commit()

        # Ensure products table has loader_url
        _cursor.execute("PRAGMA table_info(products)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "loader_url" not in _cols:
            _cursor.execute("ALTER TABLE products ADD COLUMN loader_url VARCHAR(256)")
            _conn.commit()

        # Ensure pricing_tiers table has is_subscription
        _cursor.execute("PRAGMA table_info(pricing_tiers)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "is_subscription" not in _cols:
            _cursor.execute("ALTER TABLE pricing_tiers ADD COLUMN is_subscription BOOLEAN DEFAULT 0")
            _conn.commit()

        # Ensure pricing_tiers table has sellix_product_id
        _cursor.execute("PRAGMA table_info(pricing_tiers)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "sellix_product_id" not in _cols:
            _cursor.execute("ALTER TABLE pricing_tiers ADD COLUMN sellix_product_id VARCHAR(64)")
            _conn.commit()

        # Ensure orders table has stripe_subscription_id
        _cursor.execute("PRAGMA table_info(orders)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "stripe_subscription_id" not in _cols:
            _cursor.execute("ALTER TABLE orders ADD COLUMN stripe_subscription_id VARCHAR(128)")
            _conn.commit()

        # Ensure keys table has is_subscription
        _cursor.execute("PRAGMA table_info(keys)")
        _cols = [r[1] for r in _cursor.fetchall()]
        if "is_subscription" not in _cols:
            _cursor.execute("ALTER TABLE keys ADD COLUMN is_subscription BOOLEAN DEFAULT 0")
            _conn.commit()

        # Ensure keys table has tier_id, assigned_at
        _cursor.execute("PRAGMA table_info(keys)")
        _key_cols = [r[1] for r in _cursor.fetchall()]
        if "tier_id" not in _key_cols:
            _cursor.execute("ALTER TABLE keys ADD COLUMN tier_id INTEGER REFERENCES pricing_tiers(id)")
            _conn.commit()
        if "assigned_at" not in _key_cols:
            _cursor.execute("ALTER TABLE keys ADD COLUMN assigned_at DATETIME")
            _conn.commit()

        _cursor.close()
        _conn.close()
    except Exception:
        pass

    try:
        mn_conn = db.engine.raw_connection()
        mc = mn_conn.cursor()
        for col, ddl in [
            ("bundle_count", "INTEGER DEFAULT 1"),
            ("ivno_subscription_link", "VARCHAR(512)"),
            ("billing_type", "VARCHAR(16) DEFAULT 'one_time'"),
            ("is_subscription", "BOOLEAN DEFAULT 0"),
            ("visibility", "VARCHAR(16) DEFAULT 'public'"),
            ("features_text", "TEXT"),
            ("buyer_notes", "TEXT"),
            ("venomcheats_data", "TEXT"),
            ("last_synced_at", "DATETIME"),
            ("gallery_images", "TEXT"),
            ("license_api_app_id", "VARCHAR(64)"),
            ("updated_at", "DATETIME"),
            ("status", "VARCHAR(16) DEFAULT 'undetected'"),
            ("loader_url", "VARCHAR(256)"),
            ("game", "VARCHAR(64)"),
        ]:
            try:
                mc.execute("ALTER TABLE products ADD COLUMN {} {}".format(col, ddl))
            except Exception:
                pass
        for col, ddl in [
            ("bundle_count", "INTEGER DEFAULT 1"),
            ("ivno_subscription_link", "VARCHAR(512)"),
            ("billing_type", "VARCHAR(16) DEFAULT 'one_time'"),
            ("is_subscription", "BOOLEAN DEFAULT 0"),
        ]:
            try:
                mc.execute("ALTER TABLE pricing_tiers ADD COLUMN {} {}".format(col, ddl))
            except Exception:
                pass
        for col, ddl in [
            ("is_subscription", "BOOLEAN DEFAULT 0"),
            ("tier_id", "INTEGER REFERENCES pricing_tiers(id)"),
            ("assigned_at", "DATETIME"),
        ]:
            try:
                mc.execute("ALTER TABLE keys ADD COLUMN {} {}".format(col, ddl))
            except Exception:
                pass
        for col, ddl in [
            ("quantity", "INTEGER DEFAULT 1"),
            ("stripe_subscription_id", "VARCHAR(128)"),
        ]:
            try:
                mc.execute("ALTER TABLE orders ADD COLUMN {} {}".format(col, ddl))
            except Exception:
                pass
        mn_conn.commit()
        mc.close()
        mn_conn.close()
    except Exception:
        pass

    try:
        from utils.kv_store import (
            restore_users_to_db, restore_products_to_db,
            restore_orders_to_db, restore_keys_to_db, restore_settings_to_db,
            start_backup_thread,
        )
        restore_users_to_db()
        restore_products_to_db()
        restore_orders_to_db()
        restore_keys_to_db()
        restore_settings_to_db()
        start_backup_thread(app, interval=120)
    except Exception:
        pass

    # Ensure license_api_app_id column exists on MySQL
    try:
        from sqlalchemy import text
        db.session.execute(text("ALTER TABLE products ADD COLUMN license_api_app_id VARCHAR(64)"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # One-time (idempotent) sync: keep pricing_tiers.billing_type aligned with
    # is_subscription. Historically these drifted because add_tier set only
    # billing_type while the private-product seed set only is_subscription, and
    # the storefront reads billing_type while admin/cheats read is_subscription.
    # is_subscription is treated as the source of truth.
    try:
        from models import PricingTier
        synced = 0
        for _t in PricingTier.query.all():
            _want = "subscription" if _t.is_subscription else "one_time"
            if (_t.billing_type or "one_time") != _want:
                _t.billing_type = _want
                synced += 1
        if synced:
            db.session.commit()
            print(f"Synced {synced} pricing tier(s): billing_type aligned with is_subscription.")
    except Exception as _e:
        db.session.rollback()
        print("Tier sync migration skipped:", _e)

    # One-time (idempotent) rewrite: the Discord invite moved to
    # https://discord.gg/X8yQuMYsxp. Any stored discord_public_url still
    # pointing at the old invite is rewritten so the storefront picks up
    # the new link without manual Settings edits. A deliberately custom
    # URL (anything other than the known old invite) is left untouched.
    try:
        from models import Setting
        _old_invites = {
            "https://discord.gg/bU4tFA43KK",
            "http://discord.gg/bU4tFA43KK",
        }
        _stored = Setting.get("discord_public_url")
        if _stored and _stored.strip().rstrip("/") in _old_invites:
            Setting.set("discord_public_url", "https://discord.gg/X8yQuMYsxp")
            print("Discord invite updated to the new server link.")
    except Exception as _e:
        print("Discord invite rewrite skipped:", _e)

    seed_products()

    try:
        from utils.sync import start_sync_service
        start_sync_service(app)
    except Exception:
        pass


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
