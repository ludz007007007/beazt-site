import logging
import json
import os
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

_sync_thread = None
_stop_event = threading.Event()
_last_sync = None


_DAILY_TICK_SECONDS = 86400  # VenomCheats sync runs once per day


def _run_sync(app):
    """Background loop: VenomCheats daily sync."""
    logger.info("Background sync thread started (VenomCheats daily)")
    while not _stop_event.is_set():
        _stop_event.wait(timeout=_DAILY_TICK_SECONDS)
        if _stop_event.is_set():
            break
        with app.app_context():
            try:
                _perform_sync(app)
            except Exception as e:
                logger.error("Daily VenomCheats sync failed: %s", e)


def _perform_sync(app):
    """Execute a full sync cycle."""
    from models import db, Product, Setting
    from utils.venomcheats import sync_all, get_rating

    logger.info("Starting daily VenomCheats sync")
    static_dir = os.path.join(app.root_path, "static")
    vc_data = sync_all(static_dir=static_dir)

    if not vc_data:
        logger.warning("No VenomCheats data received during daily sync")
        return

    products = Product.query.all()
    updated = 0
    for product in products:
        from routes.admin import _enrich_product_from_venomcheats
        if _enrich_product_from_venomcheats(product):
            updated += 1

    rating = get_rating()
    if rating:
        existing = Setting.query.filter_by(key="venomcheats_rating").first()
        if existing:
            existing.value = json.dumps(rating)
        else:
            db.session.add(Setting(key="venomcheats_rating", value=json.dumps(rating)))

    db.session.commit()
    global _last_sync
    _last_sync = datetime.utcnow()
    logger.info("Daily VenomCheats sync complete: %d products, %d updated", len(vc_data), updated)


def start_sync_service(app):
    """Start the background daily sync thread."""
    global _sync_thread, _stop_event

    if _sync_thread and _sync_thread.is_alive():
        logger.info("Sync service already running")
        return

    _stop_event.clear()
    _sync_thread = threading.Thread(target=_run_sync, args=(app,), daemon=True)
    _sync_thread.start()
    logger.info("Sync service started (VenomCheats daily)")


def stop_sync_service():
    """Stop the background sync thread."""
    global _stop_event
    _stop_event.set()
    logger.info("VenomCheats sync service stopped")


def get_last_sync_time():
    """Return the timestamp of the last completed sync."""
    return _last_sync
