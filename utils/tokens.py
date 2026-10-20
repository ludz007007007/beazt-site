"""HMAC-signed, single-use password-reset tokens (VAL-AUTH-004).

Token shape: ``<user_id>.<expires_epoch>.<nonce>.<hmac_sha256>`` — signed
with SECRET_KEY (itsdangerous-style HMAC-SHA256, stdlib only, no new
dependency), 1h TTL. Only a SHA-256 hash of the full token is ever
persisted (models.PasswordResetToken); a database leak therefore never
yields a usable reset link. The stored row exists purely to enforce single
use and lets us refuse correctly-signed tokens we never issued.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

RESET_TOKEN_TTL = timedelta(hours=1)


def _sign(payload):
    from flask import current_app

    key = current_app.config["SECRET_KEY"]
    if isinstance(key, str):
        key = key.encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_reset_token(user_id, expires_at=None):
    """Create a signed reset token for ``user_id`` (1h TTL by default).

    ``expires_at`` (UTC datetime) exists for tests that need to mint expired
    tokens through the same signing path.
    """
    expires = expires_at or datetime.utcnow() + RESET_TOKEN_TTL
    expires_epoch = int(expires.timestamp())
    payload = f"{user_id}.{expires_epoch}.{secrets.token_hex(16)}"
    return f"{payload}.{_sign(payload)}"


def verify_reset_token(token):
    """Verify signature and TTL.

    Returns ``(user_id, error)`` where error is ``"invalid"``, ``"expired"``
    or ``None``. Single-use tracking is handled by the caller via the stored
    token-hash row.
    """
    parts = (token or "").split(".")
    if len(parts) != 4:
        return None, "invalid"
    uid_s, exp_s, nonce, signature = parts
    payload = f"{uid_s}.{exp_s}.{nonce}"
    try:
        if not hmac.compare_digest(_sign(payload), signature):
            return None, "invalid"
        user_id = int(uid_s)
        expires = int(exp_s)
    except (TypeError, ValueError):
        return None, "invalid"
    if datetime.utcnow().timestamp() >= expires:
        return user_id, "expired"
    return user_id, None


def hash_token(token):
    """SHA-256 hex digest of a token — the only form ever persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
