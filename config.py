"""Application configuration.

SECRETS HYGIENE (see AGENTS.md "Security Conventions" #4):
    NEVER hardcode real API keys, secrets, tokens, or session cookies in this
    file or anywhere else in the repo. All third-party credentials (IVNO,
    License API, SMTP, ChairFBI, loader tokens, ...) must come exclusively
    from environment variables (.env locally, platform env vars in
    production). Defaults must be empty strings or non-secret placeholders,
    never real credential values. Cookie jars (cookies*.txt, *.cookies) are
    git-ignored and must stay untracked. If a credential was ever committed,
    it is burned: rotate it with the provider (user action) and never
    re-commit it.
"""

import os
import secrets as _secrets
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))

_IS_DEBUG = os.getenv("FLASK_DEBUG", os.getenv("DEBUG", "")).strip().lower() in (
    "1", "true", "yes", "on",
)


def _resolve_secret_key():
    """SECRET_KEY sourcing (see AGENTS.md secrets-hygiene convention).

    1. SECRET_KEY env var always wins.
    2. Dev fallback ('dev-secret-change-in-production') ONLY when FLASK_DEBUG
       / DEBUG is truthy — never in production mode.
    3. Non-debug without a configured key: generate a random key and persist
       it to instance/secret_key so sessions survive restarts, with a loud
       warning. This keeps local `uv run` development working (the service
       manifest starts the app with debug disabled) without shipping a weak
       hardcoded key.
    """
    env_key = os.getenv("SECRET_KEY", "").strip()
    if env_key:
        return env_key
    if _IS_DEBUG:
        return "dev-secret-change-in-production"
    try:
        key_file = os.path.join(basedir, "instance", "secret_key")
        if os.path.exists(key_file):
            with open(key_file, "r") as f:
                existing = f.read().strip()
            if existing:
                return existing
        key = _secrets.token_hex(32)
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        with open(key_file, "w") as f:
            f.write(key)
        print(
            "WARNING: SECRET_KEY is not set — generated a random key and "
            "persisted it to instance/secret_key. Set SECRET_KEY in the "
            "environment for production deployments."
        )
        return key
    except Exception:
        print(
            "WARNING: SECRET_KEY is not set and a generated key could not be "
            "persisted — using an ephemeral random key (sessions will not "
            "survive restarts). Set SECRET_KEY in the environment."
        )
        return _secrets.token_hex(32)


class Config:
    SECRET_KEY = _resolve_secret_key()
    # Session cookie hardening (VAL-SEC-004):
    # SameSite=Lax mitigates cross-site request forgery on POSTs while keeping
    # normal top-level navigation working. SESSION_COOKIE_SECURE is opt-in via
    # env (set SESSION_COOKIE_SECURE=true in production behind HTTPS); it must
    # stay off by default because the dev server runs on plain HTTP, where a
    # Secure cookie would silently break logins.
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = os.getenv(
        "SESSION_COOKIE_SECURE", ""
    ).strip().lower() in ("1", "true", "yes", "on")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(basedir, "instance", "beazt.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SITE_URL = os.getenv("SITE_URL", "http://localhost:5000")
    DISCORD_PUBLIC_URL = os.getenv("DISCORD_PUBLIC_URL", "https://discord.gg/X8yQuMYsxp")
    DISCORD_PRIVATE_URL = os.getenv("DISCORD_PRIVATE_URL", "")
    CHAIRFBI_API_TOKEN = os.getenv("CHAIRFBI_API_TOKEN", "")
    CHAIRFBI_API_BASE = os.getenv("CHAIRFBI_API_BASE", "https://access.chairfbi.com")
    LOADER_TOKEN = os.getenv("LOADER_TOKEN", "")
    LOADER_URL = os.getenv("LOADER_URL", "")
    # Third-party payment/license credentials: env-only, no hardcoded values.
    # Empty defaults intentionally disable these integrations until configured
    # via environment variables or the admin Settings page (database-backed
    # settings take precedence in the get_*_config() helpers below).
    IVNO_API_KEY = os.getenv("IVNO_API_KEY", "")
    IVNO_API_SECRET = os.getenv("IVNO_API_SECRET", "")
    IVNO_WEBHOOK_SECRET = os.getenv("IVNO_WEBHOOK_SECRET", "")
    # NFAHub reseller API (account storefront fulfillment). Optional: empty
    # key disables the integration exactly like the other paid suppliers.
    NFAHUB_API_KEY = os.getenv("NFAHUB_API_KEY", "")
    NFAHUB_API_BASE = os.getenv("NFAHUB_API_BASE", "https://nfahub.cc/api/reseller/v2")
    LOADER_PUBLIC_URL = os.getenv("LOADER_PUBLIC_URL", "")
    LOADER_PRIVATE_URL = os.getenv("LOADER_PRIVATE_URL", "")
    IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")
    LICENSE_API_URL = os.getenv("LICENSE_API_URL", "http://panel.projectinfinity.co.za:3845")
    LICENSE_API_TOKEN = os.getenv("LICENSE_API_TOKEN", "")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASS = os.getenv("SMTP_PASS", "")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1") not in ("0", "false", "False", "")
    SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
    SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "BEAZT")


# Startup visibility: make it obvious which paid integrations are disabled
# because their credentials are not configured (instead of failing silently
# later during checkout or key generation).
_MISSING_CREDENTIALS = [
    name for name, value in (
        ("IVNO_API_KEY", Config.IVNO_API_KEY),
        ("IVNO_API_SECRET", Config.IVNO_API_SECRET),
        ("LICENSE_API_TOKEN", Config.LICENSE_API_TOKEN),
    ) if not value
]
if _MISSING_CREDENTIALS:
    print(
        "WARNING: " + ", ".join(_MISSING_CREDENTIALS)
        + " not set in environment — the related integrations (IVNO card "
        "payments, License API key generation) are disabled until these are "
        "configured via env vars or the admin Settings page."
    )


def get_chairfbi_config():
    from models import Setting

    def _lookup(key, default):
        try:
            val = Setting.get(key)
            if val:
                return val
        except Exception:
            pass
        return default

    return {
        "api_token": _lookup("chairfbi_api_token", Config.CHAIRFBI_API_TOKEN),
        "api_base": _lookup("chairfbi_api_base", Config.CHAIRFBI_API_BASE),
    }

def get_loader_config():
    from models import Setting

    def _lookup(key, default):
        try:
            val = Setting.get(key)
            if val:
                return val
        except Exception:
            pass
        return default

    return {
        "loader_token": _lookup("loader_token", Config.LOADER_TOKEN),
        "loader_url": _lookup("loader_url", Config.LOADER_URL),
        "loader_public_url": _lookup("loader_public_url", Config.LOADER_PUBLIC_URL),
        "loader_private_url": _lookup("loader_private_url", Config.LOADER_PRIVATE_URL),
    }

def get_ivno_config():
    from models import Setting

    def _lookup(key, default):
        try:
            val = Setting.get(key)
            if val:
                return val
        except Exception:
            pass
        return default

    return {
        "api_key": _lookup("ivno_api_key", Config.IVNO_API_KEY),
        "api_secret": _lookup("ivno_api_secret", Config.IVNO_API_SECRET),
        "webhook_secret": _lookup("ivno_api_secret", Config.IVNO_WEBHOOK_SECRET),
    }

def get_discord_config():
    from models import Setting

    def _lookup(key, default):
        try:
            val = Setting.get(key)
            if val:
                return val
        except Exception:
            pass
        return default

    return {
        "public_url": _lookup("discord_public_url", Config.DISCORD_PUBLIC_URL),
        "private_url": _lookup("discord_private_url", Config.DISCORD_PRIVATE_URL),
    }

def get_nfahub_config():
    """NFAHub reseller API credentials (utils/nfahub.py).

    Mirrors the other integration helpers: Settings take precedence over the
    Config env-var defaults, so the key / base URL can be updated from the
    admin Settings page without a redeploy.
    """
    from models import Setting

    def _lookup(key, default):
        try:
            val = Setting.get(key)
            if val:
                return val
        except Exception:
            pass
        return default

    return {
        "api_key": _lookup("nfahub_api_key", Config.NFAHUB_API_KEY),
        "api_base": _lookup("nfahub_api_base", Config.NFAHUB_API_BASE),
    }

def get_license_api_config():
    """License API (Project Infinity / CatNip panel) credentials.

    Mirrors the other integration helpers: Settings take precedence over the
    Config env-var defaults, so the token / URL / auth scheme can be updated
    from the admin Settings page without a redeploy.
    """
    from models import Setting

    def _lookup(key, default):
        try:
            val = Setting.get(key)
            if val:
                return val
        except Exception:
            pass
        return default

    scheme = _lookup("license_api_auth_scheme", "raw").strip().lower()
    if scheme not in ("bearer", "raw"):
        scheme = "raw"
    return {
        "api_token": _lookup("license_api_token", Config.LICENSE_API_TOKEN),
        "api_url": _lookup("license_api_url", Config.LICENSE_API_URL),
        "auth_scheme": scheme,
    }

def get_mailer_config():
    """SMTP credentials for the transactional mailer.

    Settings take precedence over Config env defaults so SMTP can be updated
    from the admin Settings page without a redeploy.
    """
    from models import Setting

    def _lookup(key, default):
        try:
            val = Setting.get(key)
            if val:
                return val
        except Exception:
            pass
        return default

    use_tls_val = _lookup("smtp_use_tls", "1" if Config.SMTP_USE_TLS else "0")
    use_tls = str(use_tls_val).strip().lower() in ("1", "true", "yes", "on")
    return {
        "smtp_host": _lookup("smtp_host", Config.SMTP_HOST),
        "smtp_port": _lookup("smtp_port", str(Config.SMTP_PORT)),
        "smtp_user": _lookup("smtp_user", Config.SMTP_USER),
        "smtp_pass": _lookup("smtp_pass", Config.SMTP_PASS),
        "use_tls": use_tls,
        "from_email": _lookup("smtp_from_email", Config.SMTP_FROM_EMAIL),
        "from_name": _lookup("smtp_from_name", Config.SMTP_FROM_NAME),
    }
