import logging
import json
import os
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_sync_thread = None
_stop_event = threading.Event()
_last_sync = None


_NFA_TICK_SECONDS = 300      # NFA stock + auto-delivery every 5 minutes
_DAILY_TICKS = 288           # 24h of 5-minute ticks for the VenomCheats sync

def _run_sync(app):
    """Background loop: NFA stock/delivery every 5 min, Venom daily."""
    logger.info("Background sync thread started (NFA every %ds, Venom daily)",
                _NFA_TICK_SECONDS)
    tick = 0
    while not _stop_event.is_set():
        _stop_event.wait(timeout=_NFA_TICK_SECONDS)
        if _stop_event.is_set():
            break
        with app.app_context():
            try:
                _sync_nfahub_stock(app)
            except Exception as e:
                logger.error("NFA stock sync failed: %s", e)
            try:
                _deliver_awaiting_nfahub(app)
            except Exception as e:
                logger.error("NFA auto-delivery pass failed: %s", e)
            if tick % _DAILY_TICKS == _DAILY_TICKS - 1:
                try:
                    _perform_sync(app)
                except Exception as e:
                    logger.error("Daily VenomCheats sync failed: %s", e)
        tick += 1

def _sync_nfahub_stock(app):
    """Refresh PricingTier.nfahub_stock from the live NFAHub catalog."""
    from models import db, PricingTier
    from utils.nfahub import stock_map

    smap = stock_map()
    if not smap:
        return
    updated = 0
    for tier in (PricingTier.query
                 .filter(PricingTier.nfahub_variant_id.isnot(None)).all()):
        stock = smap.get((tier.nfahub_variant_id or "").strip())
        if stock is not None and stock != tier.nfahub_stock:
            tier.nfahub_stock = stock
            updated += 1
    if updated:
        db.session.commit()
    logger.info("NFAHub stock synced (%d tier(s) updated)", updated)

def _deliver_awaiting_nfahub(app):
    """Retry fulfillment for NFA orders stuck in awaiting_keys.

    Covers NFAHub's status:"review" window being longer than the checkout
    poll: the buy used the order-scoped Idempotency-Key, so re-running
    handle_fulfillment returns the SAME purchase (never a double charge)
    and completes + emails the buyer the moment the activation key exists.
    """
    from models import Order
    from routes.checkout import handle_fulfillment

    for order in Order.query.filter_by(status="awaiting_keys").all():
        tier = order.tier
        if tier and (tier.nfahub_variant_id or "").strip():
            logger.info("Auto-delivery retry for awaiting NFA order %s", order.id)
            handle_fulfillment(order)


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
    logger.info("Sync service started (NFA stock/delivery every %ds, Venom daily)",
                _NFA_TICK_SECONDS)


def stop_sync_service():
    """Stop the background sync thread."""
    global _stop_event
    _stop_event.set()
    logger.info("VenomCheats sync service stopped")


def get_last_sync_time():
    """Return the timestamp of the last completed sync."""
    return _last_sync
