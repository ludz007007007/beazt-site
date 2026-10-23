import logging
import os
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

logger = logging.getLogger(__name__)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    keys = db.relationship("Key", backref="user", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class PasswordResetToken(db.Model):
    """Single-use marker for a password-reset token (VAL-AUTH-004).

    The token itself is HMAC-signed and stateless (utils/tokens.py); this row
    exists only to invalidate it after use and to refuse correctly-signed
    tokens we never issued. Only the SHA-256 hash is stored — never a usable
    token — so a database leak cannot produce working reset links.
    """

    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User")


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    slug = db.Column(db.String(128), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(256), nullable=True)
    is_private = db.Column(db.Boolean, default=False)
    chairfbi_cheat_id = db.Column(db.String(64), nullable=True)
    license_api_app_id = db.Column(db.String(64), nullable=True)
    key_source = db.Column(db.String(16), default="chairfbi")
    visibility = db.Column(db.String(16), default="public")
    features_text = db.Column(db.Text, nullable=True)
    buyer_notes = db.Column(db.Text, nullable=True)
    gallery_images = db.Column(db.Text, nullable=True)
    venomcheats_slug = db.Column(db.String(64), nullable=True)
    venomcheats_data = db.Column(db.Text, nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(16), default="undetected")
    # Set when an operator last confirmed the build works on the current game
    # version; storefront freshness labels read this, never the render time.
    last_verified_at = db.Column(db.DateTime, nullable=True)
    loader_url = db.Column(db.String(256), nullable=True)
    # Showcase video (YouTube watch URL); rendered as an embedded player on
    # the product page when set.
    video_url = db.Column(db.String(256), nullable=True)
    # Admin-controlled pin: featured products sort to the top of the homepage
    # showcase and the catalogue. Not set by any automatic rule.
    is_featured = db.Column(db.Boolean, default=False, index=True)
    # Game/category this product belongs to (e.g. "Rust"). Free-text set by the
    # admin; storefront groups products and builds /games/<slug> pages from it.
    game = db.Column(db.String(64), nullable=True, index=True)

    tiers = db.relationship("PricingTier", backref="product", lazy="dynamic")

    @property
    def youtube_embed_url(self):
        """Embed-ready URL for video_url, or None if unset/not a YouTube link.

        Accepts the usual watch/shorts/youtu.be forms; anything else returns
        None so the template simply skips the showcase block.
        """
        import re as _re
        if not self.video_url:
            return None
        m = _re.search(
            r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([\w-]{6,})",
            self.video_url,
        )
        return "https://www.youtube-nocookie.com/embed/" + m.group(1) if m else None

    @property
    def game_slug(self):
        """URL-safe slug for the game ("Counter-Strike 2" -> "counter-strike-2").

        Falls back to the display game (derived from the product slug) so
        products without an admin-set game still group and link consistently.
        """
        import re as _re
        name = self.game or self.display_game
        if not name:
            return ""
        return _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    @property
    def display_game(self):
        """Game name for display; falls back to the first slug token."""
        if self.game:
            return self.game
        return self.slug.split("-")[0].capitalize() if self.slug else "Other"


class PricingTier(db.Model):
    __tablename__ = "pricing_tiers"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    label = db.Column(db.String(64), nullable=False)
    duration_days = db.Column(db.Integer, nullable=False)
    price_pence = db.Column(db.Integer, nullable=False)
    stripe_price_id = db.Column(db.String(128), nullable=True)
    billing_type = db.Column(db.String(16), default="one_time")
    ivno_subscription_link = db.Column(db.String(512), nullable=True)
    bundle_count = db.Column(db.Integer, default=1)
    is_subscription = db.Column(db.Boolean, default=False)
    sellix_product_id = db.Column(db.String(64), nullable=True)
    # NFAHub reseller catalog variant this tier fulfils from (utils/nfahub.py).
    # Empty means the tier is not backed by NFAHub even on nfahub products.
    nfahub_variant_id = db.Column(db.String(64), nullable=True)
    # Live stock for the bound variant, refreshed by the sync service
    # (utils/sync.py). NULL = unknown (never synced) — treated as in stock.
    nfahub_stock = db.Column(db.Integer, nullable=True)

    orders = db.relationship("Order", backref="tier", lazy="dynamic")
    keys = db.relationship("Key", backref="pricing_tier", lazy="dynamic")

    @property
    def price_pounds(self):
        return self.price_pence / 100


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    tier_id = db.Column(db.Integer, db.ForeignKey("pricing_tiers.id"), nullable=False)
    stripe_session_id = db.Column(db.String(128), unique=True, nullable=True)
    stripe_subscription_id = db.Column(db.String(128), nullable=True)
    status = db.Column(db.String(32), default="pending")
    quantity = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    key = db.relationship("Key", backref="order", uselist=False)


class Key(db.Model):
    __tablename__ = "keys"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    tier_id = db.Column(db.Integer, db.ForeignKey("pricing_tiers.id"), nullable=True)
    key_value = db.Column(db.String(128), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assigned_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    is_subscription = db.Column(db.Boolean, default=False)
    chairfbi_key_id = db.Column(db.String(64), nullable=True, index=True)
    chairfbi_cheat_id = db.Column(db.String(32), nullable=True)
    # NFAHub purchase this key was fulfilled from (for warranty/support lookups).
    nfahub_order_id = db.Column(db.String(64), nullable=True, index=True)

    product = db.relationship("Product")
    tier = db.relationship("PricingTier", overlaps="keys,pricing_tier")


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)

    @staticmethod
    def get(key, default=None):
        row = db.session.execute(
            db.select(Setting).filter_by(key=key)
        ).scalar_one_or_none()
        return row.value if row and row.value else default

    @staticmethod
    def set(key, value):
        row = db.session.execute(
            db.select(Setting).filter_by(key=key)
        ).scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.session.add(Setting(key=key, value=value))
        db.session.commit()


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    # Optional link to the fulfilled order that qualified the buyer.
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=True, index=True)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    title = db.Column(db.String(128), nullable=True)
    body = db.Column(db.Text, nullable=False)
    # pending -> approved (shown publicly) | rejected. Admin-moderated.
    status = db.Column(db.String(16), default="pending", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref="reviews")
    product = db.relationship("Product", backref="reviews")
    order = db.relationship("Order", backref="review", uselist=False)

    @property
    def display_name(self):
        """Buyer name shown publicly (username, never email)."""
        return self.user.username if self.user else "Verified buyer"


class StatusEvent(db.Model):
    """Append-only history of product status changes (detection-status evidence)."""

    __tablename__ = "status_events"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False)
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    product = db.relationship(
        "Product",
        backref=db.backref("status_events", lazy="dynamic", order_by="StatusEvent.created_at.desc()"),
    )


def seed_admin():
    """Create/refresh the super-admin account from ADMIN_EMAIL/ADMIN_PASSWORD.

    Security (VAL-SEC-002): there is NO hardcoded fallback password and NO
    default email. If either env var is unset on first run, no admin is
    created and a startup warning explains how to bootstrap one
    (set the env vars, or run scripts/seed_demo.py for a local dev admin).
    """
    admin_username = "admin"
    admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    admin_password = (os.getenv("ADMIN_PASSWORD") or "").strip()

    admin_user = User.query.filter_by(username=admin_username).first()
    if admin_user is None and admin_email:
        admin_user = User.query.filter_by(email=admin_email).first()

    if admin_user is None:
        if not (admin_email and admin_password):
            print(
                "WARNING: ADMIN_EMAIL and/or ADMIN_PASSWORD not set — no admin "
                "account created. Set both env vars and restart, or run "
                "scripts/seed_demo.py to create a local admin."
            )
            return

        admin_user = User(
            username=admin_username,
            email=admin_email,
            is_admin=True,
            is_active=True,
        )
        admin_user.set_password(admin_password)
        db.session.add(admin_user)
        db.session.commit()
        print("Super admin account created from ADMIN_EMAIL/ADMIN_PASSWORD.")
    else:
        # Existing admin: never touch the password here. The password may have
        # been changed via /profile, and re-seeding it on every boot would
        # silently revert that change. Only sync account flags.
        changed = False

        if admin_user.username != admin_username:
            username_owner = User.query.filter_by(username=admin_username).first()
            if username_owner is None or username_owner.id == admin_user.id:
                admin_user.username = admin_username
                changed = True

        if not admin_user.is_admin:
            admin_user.is_admin = True
            changed = True

        if not admin_user.is_active:
            admin_user.is_active = True
            changed = True

        if changed:
            db.session.commit()
            print("Super admin account synced.")


def seed_products():
    """Seed the database with the Rust External Private product and its pricing tiers."""
    seed_admin()

    if Product.query.count() == 0:
        product = Product(
            name="Rust External - BeaZt Legit",
            slug="rust-external-private",
            description=(
                "Premium external performance suite with privacy-mode overlay "
                "and read-only architecture. Exclusive access with continuous "
                "updates and community support."
            ),
            features_text=(
                "Legit ESP suite with player and resource overlays\n"
                "Debug camera with free-roam spectator mode\n"
                "Distance and visibility tools with configurable ranges\n"
                "Legit-focused aim presets with natural curves\n"
                "Stream-safe privacy-mode overlay\n"
                "Private build with anti-detection updates\n"
                "Priority Discord setup support"
            ),
            buyer_notes=(
                "Windows 10/11 with a stable Rust install required\n"
                "Fast onboarding with Discord walkthrough guide\n"
                "Ticketed help for setup, HWID reset, and maintenance\n"
                "Loader download available in My Keys dashboard"
            ),
            image_url=None,
            is_private=False,
            key_source="pool",
            # Pool-key products are BeaZt-operated: app.py's one-time migration
            # marks key_source='pool' rows visibility='private'. Mirror that
            # here so fresh databases seed one private product and the
            # store/homepage Private Software sections have data to render.
            visibility="private",
        )
        db.session.add(product)
        db.session.flush()

        tiers = [
            PricingTier(
                product_id=product.id,
                label="1 Day",
                duration_days=1,
                price_pence=900,
            ),
            PricingTier(
                product_id=product.id,
                label="1 Week",
                duration_days=7,
                price_pence=2500,
            ),
            PricingTier(
                product_id=product.id,
                label="1 Month",
                duration_days=30,
                price_pence=4900,
            ),
            PricingTier(
                product_id=product.id,
                label="1 Year",
                duration_days=365,
                price_pence=39600,
            ),
        ]
        for tier in tiers:
            db.session.add(tier)

        db.session.commit()
        print("Database seeded with Performance Suite product.")
