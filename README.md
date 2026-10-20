# BEAZT

BEAZT is a premium private-software storefront built with Python/Flask. It provides a product catalog, account management, paid checkout with automatic license-key fulfillment, a customer "My Keys" dashboard, and a full admin panel for products, orders, keys, users, and integration settings.

## Features

- **Store** — catalog homepage and `/cheats` listing render the **full live catalogue** (every product, grouped by game, with search/status/sort filters), product detail pages with image galleries, feature lists, pricing tiers (one-time and subscription billing), and buyer notes; per-game landing pages under `/games/<game>`, a `/status` board, and DB-backed verified reviews.
- **Auth** — login, signup, and logout with per-session CSRF protection and hashed passwords.
- **Checkout** — gateway sessions for PayFast and IVNO; server-to-server webhooks verify payments and fulfill orders automatically.
- **Dashboard (My Keys)** — customers view and manage their license keys; loader downloads are available per key.
- **Reviews / feedback** — `/feedback` page with community proof.
- **Content pages** — FAQ, loader guide (`/loader`, `/loader/<slug>`), terms of service, and privacy policy; custom 404 page.
- **Admin panel** (`/admin`) — product and tier management (create, import/export CSV, bulk delete), order fulfillment (pool keys, custom keys, license-API retry), key management, user management (impersonation, enable/disable, delete), ChairFBI/License API key operations (import, HWID reset, revoke, delete-unused-key, vouch), VenomCheat sync, and a database-backed Settings page with a License API "Test Connection" form.
- **Health endpoints** — `/health/products` and `/health/kv` for operational checks (admin-only; anonymous requests redirect to login).

## Tech Stack

- **Backend:** Python 3, Flask 3, Flask-SQLAlchemy, Flask-Login
- **Database:** SQLite (default, `instance/beazt.db`); PyMySQL included for MySQL option via `DATABASE_URL`
- **Templates:** Jinja2
- **Frontend:** Alpine.js and Lucide icons, vendored in `static/js/vendor/` (injected after page load); self-hosted fonts (Archivo variable, Inter, JetBrains Mono) in `static/fonts/`
- **CSS:** the "SIGNAL" design system — source stylesheets in `static/css/src/` (`tokens.css`, `base.css`, `site.css`, `components.css`, `admin.css`) compiled by `node scripts/build-css.mjs` into the minified bundles `static/css/style.css` and `static/css/admin.css` (pytest-enforced budgets: ≤ 80KB / ≤ 12KB). See `DESIGN_TOKENS.md` and `docs/design-system.md`.
- **Payments:** PayFast (redirect + ITN webhook), IVNO (subscription link + webhook)
- **Security:** per-session CSRF tokens, `hmac.compare_digest` validation, SameSite=Lax cookies

## Getting Started

### Prerequisites

Python 3.10+ with the [`uv`](https://docs.astral.sh/uv/) toolchain. On Windows, a bare `python` may resolve to the Microsoft Store stub — use `uv run python` instead.

### Install

```sh
uv pip install -r requirements.txt
```

### Environment variables

All secrets are sourced from the environment (`.env` locally, platform env vars in production). None are hardcoded.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Session signing key. If unset: dev fallback in debug mode, otherwise a random key is generated and persisted to `instance/secret_key`. |
| `FLASK_DEBUG` / `DEBUG` | Enables the dev-secret fallback for `SECRET_KEY`. |
| `SESSION_COOKIE_SECURE` | Set to `true` in HTTPS production (opt-in; must stay off on plain-HTTP dev). |
| `SESSION_COOKIE_SAMESITE` | Defaults to `Lax`. |
| `DATABASE_URL` | SQLAlchemy URI; defaults to `sqlite:///instance/beazt.db`. |
| `SITE_URL` | Public site URL used for external links. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Super-admin seed credentials on first run. If unset, no admin is created (see "First-run admin bootstrap" below). Set both in production. |
| `IVNO_API_KEY`, `IVNO_API_SECRET` | IVNO card-payment gateway credentials. |
| `IVNO_WEBHOOK_SECRET` | Shared secret used to authenticate IVNO webhook posts (`X-Webhook-Secret` header or `X-Webhook-Signature` HMAC-SHA256 of the raw body). Falls back to the Settings `ivno_api_secret` value when unset. |
| `LICENSE_API_URL`, `LICENSE_API_TOKEN` | License API (key generation) credentials. |
| `CHAIRFBI_API_TOKEN`, `CHAIRFBI_API_BASE` | ChairFBI panel integration. |
| `LOADER_TOKEN`, `LOADER_URL`, `LOADER_PUBLIC_URL`, `LOADER_PRIVATE_URL` | Loader distribution config. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_USE_TLS`, `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME` | Transactional mailer. |
| `IMGBB_API_KEY` | Image hosting. |

Missing payment/license credentials produce a startup warning and disable the related integrations until configured (env vars or the admin Settings page — database-backed Settings take precedence over env defaults).

### Run

```sh
uv run python app.py
```

or, to run without the debug/reloader flags that `app.py` uses by default:

```sh
uv run python -c "from app import app; app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)"
```

The app serves on port 5000.

### First-run database

The database is auto-created and auto-migrated at startup: `db.create_all()` runs in `app.py`, idempotent `ALTER TABLE` migrations add newer columns, and `seed_products()` seeds the super-admin account (from `ADMIN_EMAIL`/`ADMIN_PASSWORD`) plus a default product with four pricing tiers if the tables are empty. No manual seeding step is required.

**First-run admin bootstrap (no fallback password).** If `ADMIN_EMAIL` or `ADMIN_PASSWORD` is unset on a fresh database, **no admin account is created** — the startup log prints a warning explaining the two bootstrap paths:

1. Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in the environment (`.env`) and restart; the `admin` super-user is created on first run.
2. For local development, run the demo seed script, which creates a local admin (credentials are printed by the script) alongside demo data.

There is deliberately no hardcoded default admin password or email anywhere in the source.

## Routes

| Endpoint | Purpose |
|---|---|
| `/` | Homepage — full live catalogue (every product, grouped by game, with search/status/sort filters via GET params) |
| `/cheats` | Store listing — same shared catalogue partial as the homepage |
| `/games` | Index of all games that have products |
| `/games/<game_slug>` | Per-game landing page (all products for one game) |
| `/status` | Full live status board (real per-product statuses, no fabricated uptime) |
| `/sitemap.xml` | XML sitemap: static pages, product pages, game pages |
| `/robots.txt` | Crawler rules + sitemap reference |
| `/product/<slug>` | Product detail page (structured data, verified reviews, related products) |
| `/product/<slug>/review` (POST) | Verified-buyer review submission (moderated, CSRF-protected) |
| `/plan/<tier_id>` | Pricing-tier detail / purchase page (redirects to product page) |
| `/loader`, `/loader/<slug>` | Loader guide pages |
| `/feedback` | Reviews and proof page |
| `/faq` | FAQ page |
| `/terms-of-service`, `/privacy` | Legal pages |
| `/cheat-image/<slug>` | Product image proxy |
| `/health/products`, `/health/kv` | Health checks |
| `/my-keys` | Customer key dashboard |
| `/profile` | Account profile (GET/POST) |
| `/auth/login`, `/auth/signup`, `/auth/logout` | Authentication |
| `/checkout/create-session` (POST) | Create a PayFast or IVNO gateway session |
| `/checkout/payfast-notify` (POST) | PayFast ITN webhook — verifies payment, fulfills order |
| `/checkout/ivno-webhook` (POST) | IVNO subscription webhook |
| `/webhooks/sellix` (POST) | Legacy — returns 410 (Sellix deprecated) |
| `/admin`, `/admin/users`, `/admin/keys`, `/admin/products`, `/admin/orders`, `/admin/settings`, `/admin/chairfbi`, `/admin/reviews` | Admin panel (plus sub-routes for CRUD, fulfillment, impersonation, key operations, review moderation) |
| `/ping` | Liveness check |

## Payments and Webhooks

- **PayFast:** checkout posts to PayFast's process endpoint with merchant credentials from Settings (`payfast_merchant_id`, `payfast_merchant_key`, `payfast_passphrase`, `payfast_item_name`). Payment confirmation arrives server-to-server at `/checkout/payfast-notify` (ITN), which fulfills the order and assigns keys.
- **IVNO:** subscription products carry an `ivno_subscription_link` per tier; lifecycle events arrive at `/checkout/ivno-webhook`. Credentials: `IVNO_API_KEY` / `IVNO_API_SECRET` (env or Settings).
- **Webhook auth:** both endpoints are server-to-server, verify payloads with HMAC-style signature checks, and are deliberately **CSRF-exempt** (they carry no browser session). All other state-changing routes require a CSRF token (form field `csrf_token` or `X-CSRF-Token` header).
- `/webhooks/sellix` is retained only to return HTTP 410; Sellix is no longer supported.

## Security Notes

- Per-session CSRF tokens on all browser-facing POSTs; constant-time comparison via `hmac.compare_digest`.
- Session cookies default to `SameSite=Lax`; enable `SESSION_COOKIE_SECURE=true` behind HTTPS in production.
- All third-party credentials come exclusively from environment variables or the encrypted-by-access-control admin Settings table; no secrets are committed to the repository.
- Passwords are hashed (`werkzeug.security`); the super-admin default password only applies when `ADMIN_PASSWORD` is unset and should be rotated immediately in production.
- Dependency-free response gzip compression runs in an `after_request` hook (no extra middleware required).

## Development Notes

- **Tests.** The pytest suite lives in `tests/`. Fixtures in `tests/conftest.py` give each test a fresh schema in a throwaway SQLite file (the `instance/` database is never touched), plus `client`, `csrf_token`, `post_form`, `make_user`, `make_product`, `login`, `buyer_client`, and `admin_client` helpers. Run it with:

  ```powershell
  .venv\Scripts\python.exe -m pytest tests -q
  ```

- **Demo data.** `scripts/seed_demo.py` fills the local database with 5 demo products across Rust, Counter-Strike 2 and Apex Legends (one-time and subscription tiers; undetected, updating and detected statuses with status history), key-pool entries, demo users, orders and reviews. It is idempotent and refuses to run when `DATABASE_URL` points at a non-local or production-looking database, or when `VERCEL=1` / `FLASK_ENV=production` / `APP_ENV=production` is set. Demo logins (local only): `demo_admin` / `DemoAdmin!2026` and `demo_buyer` / `DemoBuyer!2026`.

  ```powershell
  .venv\Scripts\python.exe scripts\seed_demo.py
  ```

- **Local `.env`.** Copy `.env.example` to `.env`. It contains only synthetic PayFast/IVNO/License API values (the License API URL points at a closed local port). The seed script copies the `PAYFAST_*` values into empty Settings rows so local checkout has merchant config. Never put real credentials in `.env` during development.
- **Toolchain:** use `uv run python` (bare `python` may be a Windows Store stub on Windows).
- **Templates do not auto-reload** when the app runs with `debug=False` (as the service start command does) — restart the server after editing templates.
- **CSS pipeline.** Edit the sources in `static/css/src/` only — the built bundles are minified and token-mangled, never hand-edit them. After every CSS change run:

  ```sh
  node scripts/build-css.mjs
  ```

  The build regenerates `static/css/style.css` and `static/css/admin.css` and auto-bumps the `style.css?v=N` cache-buster in `templates/base.html` and `templates/admin/base.html`. Bump the `script.js?v=N` cache-buster manually in both base templates whenever `static/js/script.js` changes.
- **Vendored assets:** Alpine.js and Lucide live in `static/js/vendor/` and are injected after page load to avoid render blocking. Fonts are self-hosted in `static/fonts/` (woff2); only the display font (Archivo variable) is preloaded, the rest swap in via `font-display: swap`. Imagery below the fold is lazy-loaded with intrinsic dimensions.
- **Reveal animations:** a dependency-free scroll-driven reveal system is used (no ScrollReveal).
- **Accessibility:** targets WCAG 2.1 AA; interactive controls meet a 44px minimum touch-target size.
- **KV backup:** a background thread periodically snapshots the KV store (see `utils/kv_store.py`).

See `DESIGN_TOKENS.md` and `docs/design-system.md` for the design system documentation.

## Project Structure

```
app.py               # Flask app factory-ish entrypoint: CSRF, gzip, blueprints, migrations, seeding
config.py            # Env-based configuration + Settings-backed integration helpers
models.py            # SQLAlchemy models: User, Product, PricingTier, Order, Key, Setting, Review; seed_products()
routes/
  main.py            # Storefront, dashboard, content, health routes
  auth.py            # Login / signup / logout
  checkout.py        # Gateway sessions + PayFast/IVNO webhooks
  admin.py           # Admin panel (products, tiers, orders, keys, users, settings, ChairFBI)
templates/           # Jinja2 templates (site + admin/), shared components in templates/partials/
static/
  css/src/           # Stylesheet sources (tokens, base, site, components, admin)
  css/style.css      # Minified storefront bundle, built from src/ (cache-buster v50)
  css/admin.css      # Minified admin bundle, built from src/ (cache-buster v9)
  js/script.js       # Site behaviour: reveals, filters, toasts, modals, status sweep
  js/vendor/         # Vendored Alpine.js, Lucide
  fonts/             # Self-hosted Archivo variable, Inter, JetBrains Mono (woff2)
  images/            # Default OG brand card and static art
scripts/
  build-css.mjs      # Compiles static/css/src → style.css + admin.css, bumps cache-buster
  seed_demo.py       # Idempotent local demo data (see below)
  serve_dev.py       # Dev server launcher (port 5199 used by the test tooling)
  make_og_card.py    # Regenerates static/images/og-default.png
utils/               # KV store, backup thread, sync services
instance/            # Runtime: SQLite DB, generated secret_key (git-ignored)
docs/design-system.md, DESIGN_TOKENS.md   # Design system documentation
evidence/            # Validation screenshots and scripts (untracked)
requirements.txt     # Pinned Python dependencies
```
