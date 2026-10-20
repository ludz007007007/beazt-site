import os
import json
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

KV_URL = os.getenv("KV_URL", "") or os.getenv("REDIS_URL", "")
KV_AVAILABLE = bool(KV_URL)

_redis_client = None


def _get_redis():
    global _redis_client
    if not KV_AVAILABLE:
        return None
    try:
        if _redis_client is None:
            import redis as _redis
            _redis_client = _redis.from_url(
                KV_URL,
                socket_connect_timeout=5,
                socket_keepalive=True,
                retry_on_timeout=True,
            )
        _redis_client.ping()
        return _redis_client
    except Exception as e:
        logger.warning("Redis connection failed, will reconnect: %s", e)
        _redis_client = None
        return None


def kv_get(key):
    r = _get_redis()
    if r is None:
        return None
    try:
        val = r.get(key)
        if val:
            return json.loads(val)
    except Exception as e:
        logger.warning("KV get failed for %s: %s", key, e)
    return None


def kv_set(key, value, ex=2592000):
    r = _get_redis()
    if r is None:
        return False
    try:
        r.set(key, json.dumps(value, ensure_ascii=False), ex=ex)
        return True
    except Exception as e:
        logger.warning("KV set failed for %s: %s", key, e)
        return False


PRODUCT_FIELDS = [
    "name", "slug", "description", "image_url", "is_private",
    "chairfbi_cheat_id", "key_source", "visibility", "features_text",
    "buyer_notes", "venomcheats_slug", "venomcheats_data",
    "gallery_images", "last_synced_at", "created_at",
    # Persisted so restored products keep admin-set status, banner updates,
    # loader links, License API wiring, and game grouping (previously lost).
    "license_api_app_id", "updated_at", "status", "loader_url", "game",
    # Game/category label — drives homepage grouping and /games/<slug> pages.
    "game",
]


FILE_BACKUP_PATH = os.path.join(os.environ.get("TMPDIR", "/tmp"), "beazt_products.json")


def _file_backup(data):
    try:
        with open(FILE_BACKUP_PATH, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning("File backup failed: %s", e)


def _file_restore():
    try:
        if os.path.exists(FILE_BACKUP_PATH):
            with open(FILE_BACKUP_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("File restore failed: %s", e)
    return None


def backup_products():
    if not KV_AVAILABLE:
        return False
    try:
        from flask import current_app
        if not current_app:
            return False
        from models import Product, PricingTier, db

        rows = Product.query.all()
        data = []
        for p in rows:
            row = {}
            for field in PRODUCT_FIELDS:
                val = getattr(p, field, None)
                if isinstance(val, datetime):
                    val = val.isoformat()
                if isinstance(val, bytes):
                    val = val.decode("utf-8", errors="replace")
                row[field] = val
            tiers = PricingTier.query.filter_by(product_id=p.id).order_by(PricingTier.duration_days).all()
            row["_tiers"] = [{
                "label": t.label,
                "duration_days": t.duration_days,
                "price_pence": t.price_pence,
                "is_subscription": t.is_subscription,
            } for t in tiers]
            data.append(row)

        ok = kv_set("beazt_products", data)
        _file_backup(data)
        if not ok:
            logger.warning("KV write returned false — Redis may be unavailable")
        else:
            logger.info("Backed up %d products to KV", len(data))
        return True
    except Exception as e:
        logger.warning("Product backup failed: %s", e)
        return False


def restore_products():
    if not KV_AVAILABLE:
        return None
    return kv_get("beazt_products")


def restore_products_to_db():
    backup = None
    if KV_AVAILABLE:
        backup = restore_products()
    if not backup:
        backup = _file_restore()
        if backup:
            logger.info("Using /tmp file backup — %d products", len(backup))
    if not backup:
        logger.info("No KV or file backup found — fresh start")
        return

    try:
        from models import Product, PricingTier, db

        for p_data in backup:
            slug = p_data.get("slug", "")
            if not slug:
                continue
            existing = Product.query.filter_by(slug=slug).first()
            if existing:
                continue

            tiers_data = p_data.pop("_tiers", [])
            kwargs = {k: v for k, v in p_data.items() if k in PRODUCT_FIELDS}
            for dt_field in ("created_at", "last_synced_at", "updated_at"):
                if dt_field in kwargs and isinstance(kwargs[dt_field], str):
                    try:
                        kwargs[dt_field] = datetime.fromisoformat(kwargs[dt_field])
                    except (ValueError, TypeError):
                        kwargs[dt_field] = None
            product = Product(**kwargs)
            db.session.add(product)
            db.session.flush()

            for t in tiers_data:
                db.session.add(PricingTier(
                    product_id=product.id,
                    label=t.get("label", ""),
                    duration_days=int(t.get("duration_days", 1)),
                    price_pence=int(t.get("price_pence", 0)),
                    is_subscription=bool(t.get("is_subscription", False)),
                ))

        db.session.commit()
        logger.info("Restored %d products from backup", len(backup))
    except Exception as e:
        logger.warning("Product restore failed: %s", e)


USER_FIELDS = [
    "username", "email", "password_hash", "is_admin", "is_active", "created_at",
]

USER_FILE_PATH = os.path.join(os.environ.get("TMPDIR", "/tmp"), "beazt_users.json")


def _file_backup_user(data):
    try:
        with open(USER_FILE_PATH, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning("User file backup failed: %s", e)


def _file_restore_user():
    try:
        if os.path.exists(USER_FILE_PATH):
            with open(USER_FILE_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("User file restore failed: %s", e)
    return None


def backup_users():
    if not KV_AVAILABLE:
        return False
    try:
        from flask import current_app
        if not current_app:
            return False
        from models import User

        rows = User.query.all()
        data = []
        for u in rows:
            row = {}
            for field in USER_FIELDS:
                val = getattr(u, field, None)
                if isinstance(val, datetime):
                    val = val.isoformat()
                if isinstance(val, bytes):
                    val = val.decode("utf-8", errors="replace")
                row[field] = val
            data.append(row)

        ok = kv_set("beazt_users", data)
        _file_backup_user(data)
        if not ok:
            logger.warning("User KV write returned false")
        else:
            logger.info("Backed up %d users to KV", len(data))
        return True
    except Exception as e:
        logger.warning("User backup failed: %s", e)
        return False


def restore_users_to_db():
    backup = None
    if KV_AVAILABLE:
        backup = kv_get("beazt_users")
    if not backup:
        backup = _file_restore_user()
        if backup:
            logger.info("Using /tmp user file backup — %d users", len(backup))
    if not backup:
        return

    try:
        from models import User, db

        for u_data in backup:
            username = u_data.get("username", "")
            if not username:
                continue
            existing = User.query.filter_by(username=username).first()
            if existing:
                if existing.is_admin:
                    existing.password_hash = u_data.get("password_hash", existing.password_hash)
                continue

            kwargs = {k: v for k, v in u_data.items() if k in USER_FIELDS}
            ca = kwargs.get("created_at")
            if isinstance(ca, str):
                try:
                    kwargs["created_at"] = datetime.fromisoformat(ca)
                except (ValueError, TypeError):
                    kwargs["created_at"] = datetime.utcnow()
            db.session.add(User(**kwargs))

        db.session.commit()
        logger.info("Restored %d users from backup", len(backup))
    except Exception as e:
        logger.warning("User restore failed: %s", e)


_backup_thread = None
_backup_stop = threading.Event()


ORDER_FIELDS = [
    "id", "user_id", "tier_id", "stripe_session_id", "status", "created_at",
]

ORDER_FILE_PATH = os.path.join(os.environ.get("TMPDIR", "/tmp"), "beazt_orders.json")


def backup_orders():
    if not KV_AVAILABLE:
        return False
    try:
        from flask import current_app
        if not current_app:
            return False
        from models import Order, db

        rows = Order.query.order_by(Order.created_at.desc()).limit(200).all()
        data = []
        for o in rows:
            row = {}
            for field in ORDER_FIELDS:
                val = getattr(o, field, None)
                if isinstance(val, datetime):
                    val = val.isoformat()
                row[field] = val
            data.append(row)

        ok = kv_set("beazt_orders", data)
        if not ok:
            logger.warning("Order KV write failed")
        return True
    except Exception as e:
        logger.warning("Order backup failed: %s", e)
        return False


def restore_orders_to_db():
    backup = kv_get("beazt_orders") if KV_AVAILABLE else None
    if not backup:
        return
    try:
        from models import Order, db

        for o_data in backup:
            oid = o_data.get("id")
            if not oid:
                continue
            if Order.query.filter_by(id=oid).first():
                continue

            kwargs = {}
            for field in ORDER_FIELDS:
                if field == "id":
                    continue
                kwargs[field] = o_data.get(field)
            if "created_at" in kwargs and isinstance(kwargs["created_at"], str):
                try:
                    kwargs["created_at"] = datetime.fromisoformat(kwargs["created_at"])
                except (ValueError, TypeError):
                    kwargs["created_at"] = datetime.utcnow()
            kwargs["id"] = oid
            db.session.execute(Order.__table__.insert().values(**kwargs))

        db.session.commit()
        logger.info("Restored %d orders from backup", len(backup))
    except Exception as e:
        logger.warning("Order restore failed: %s", e)


KEY_FIELDS = [
    "id", "user_id", "order_id", "product_id", "tier_id",
    "key_value", "created_at", "assigned_at", "expires_at",
    "is_active", "chairfbi_key_id", "chairfbi_cheat_id", "is_subscription",
]


def backup_keys():
    if not KV_AVAILABLE:
        return False
    try:
        from flask import current_app
        if not current_app:
            return False
        from models import Key, db

        rows = Key.query.order_by(Key.created_at.desc()).limit(500).all()
        data = []
        for k in rows:
            row = {}
            for field in KEY_FIELDS:
                val = getattr(k, field, None)
                if isinstance(val, datetime):
                    val = val.isoformat()
                row[field] = val
            data.append(row)

        ok = kv_set("beazt_keys", data)
        if not ok:
            logger.warning("Key KV write failed")
        return True
    except Exception as e:
        logger.warning("Key backup failed: %s", e)
        return False


def restore_keys_to_db():
    backup = kv_get("beazt_keys") if KV_AVAILABLE else None
    if not backup:
        return
    try:
        from models import Key, db

        for k_data in backup:
            kid = k_data.get("id")
            if not kid:
                continue
            if Key.query.filter_by(id=kid).first():
                continue

            kwargs = {}
            for field in KEY_FIELDS:
                if field == "id":
                    continue
                kwargs[field] = k_data.get(field)
            for dt_field in ("created_at", "assigned_at", "expires_at"):
                if dt_field in kwargs and isinstance(kwargs[dt_field], str):
                    try:
                        kwargs[dt_field] = datetime.fromisoformat(kwargs[dt_field])
                    except (ValueError, TypeError):
                        kwargs[dt_field] = None
            kwargs["id"] = kid
            db.session.execute(Key.__table__.insert().values(**kwargs))

        db.session.commit()
        logger.info("Restored %d keys from backup", len(backup))
    except Exception as e:
        db.session.rollback()
        logger.warning("Key restore failed: %s", e)


def backup_settings():
    if not KV_AVAILABLE:
        return False
    try:
        from flask import current_app
        if not current_app:
            return False
        from models import Setting

        rows = Setting.query.all()
        data = []
        for s in rows:
            data.append({"key": s.key, "value": s.value})

        ok = kv_set("beazt_settings", data)
        if not ok:
            logger.warning("Settings KV write failed")
        return True
    except Exception as e:
        logger.warning("Settings backup failed: %s", e)
        return False


def restore_settings_to_db():
    backup = kv_get("beazt_settings") if KV_AVAILABLE else None
    if not backup:
        return
    try:
        from models import Setting, db

        for s_data in backup:
            key = s_data.get("key")
            if not key:
                continue
            existing = Setting.query.filter_by(key=key).first()
            if existing:
                continue
            db.session.add(Setting(key=key, value=s_data.get("value")))

        db.session.commit()
        logger.info("Restored %d settings from backup", len(backup))
    except Exception as e:
        logger.warning("Settings restore failed: %s", e)


def backup_everything():
    """Inline backup of all critical data. Call after state-changing ops."""
    try:
        from flask import current_app
        if not current_app:
            return
        with current_app.app_context() if hasattr(current_app, 'app_context') else __import__('contextlib').nullcontext():
            backup_products()
            backup_users()
            backup_orders()
            backup_keys()
            backup_settings()
    except Exception as e:
        logger.warning("Inline backup failed: %s", e)


def _periodic_backup(app, interval=120):
    logger.info("KV backup thread started (interval=%ds)", interval)
    while not _backup_stop.is_set():
        _backup_stop.wait(timeout=interval)
        if _backup_stop.is_set():
            break
        try:
            with app.app_context():
                backup_products()
                backup_users()
                backup_orders()
                backup_keys()
                backup_settings()
        except Exception as e:
            logger.error("Periodic backup failed: %s", e)


def start_backup_thread(app, interval=120):
    global _backup_thread, _backup_stop
    if not KV_AVAILABLE:
        logger.info("KV not configured — backup thread skipped")
        return
    if _backup_thread and _backup_thread.is_alive():
        return
    _backup_stop.clear()
    _backup_thread = threading.Thread(
        target=_periodic_backup, args=(app, interval), daemon=True
    )
    _backup_thread.start()


def stop_backup_thread():
    _backup_stop.set()
