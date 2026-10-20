# m5-performance-consistency — VAL-RSP-005 console sweep (2026-10-19)

Agent-browser headless Chrome, session 1be1329c7d2f. Console captured on load and after interactions on each key page; empty console output = zero messages (cross-verified with network requests showing no 4xx/5xx).

| Page | Viewport | Load | Interaction | Result |
|---|---|---|---|---|
| / (home) | 1440x900 | console-home-load.txt | header nav click to /cheats | 0 errors |
| / (home) | 1440x900 | netreq-home-load.txt | all resources 200 | clean |
| / (home) | 390x844 | console-home-mobile-load.txt | burger open (aria-expanded=true) + Escape close | 0 errors |
| /cheats | 1440x900 | console-cheats-load.txt | search filter auto-submit (?q=rust) | 0 errors |
| /product/cs2-rage-suite | 1440x900 | console-product-load.txt | ArrowRight tab switch (tab-features active, panel visible) + qty stepper (qty=3) | 0 errors |
| /product/cs2-rage-suite | 390x844 | console-product-mobile-load.txt | load only | 0 errors |
| /status | 1440x900 | console-status-load.txt | window.BEAZT.statusRefresh() sweep (changed: 0) | 0 errors |
| /status | 390x844 | console-status-mobile-load.txt | load only | 0 errors |
| /auth/login | 1440x900 | console-auth-load.txt | empty form submit (2 inline errors rendered) | 0 errors |
| /my-keys | 1440x900 | console-keys-load.txt | key filter chips active/all via keyboard | 0 errors |

Network cross-checks: netreq-product.txt, netreq-keys.txt (no 4xx/5xx).
Interaction state evidence: state-*.txt, console-*.txt in this directory; probes in probes/.

# Cross-page consistency sweep

Computed-style sampling of header/footer chrome (chrome_probe.js) across /, /cheats, /faq, /loader, /my-keys, /status, /feedback, /terms-of-service at 1440x900:
all IDENTICAL except the intentional active-nav highlight on /cheats (active link uses --text-primary vs --text-secondary for inactive links).
Design tokens resolve identically on every page (single tokens.css source).

# Performance checks

- style.css: 79.0 KB (budget <= 80KB, pytest-enforced); admin.css: 9.8 KB (budget <= 12KB). Build: up to date.
- Render-blocking: single stylesheet (style.css?v=50), display font preloaded (Archivo-var-latin.woff2), Alpine/Lucide injected after window load (script.js), script.js deferred.
- Images: below-fold imagery lazy-loaded with intrinsic dimensions (product_card, game_card, gallery thumbs, footer logo); above-fold product main image fetchpriority=high with width/height.
- Default OG image: og-default.png (26.6 KB, HTTP 200) rendered on non-product pages (1200x675 + alt); product pages override with per-product cover (/cheat-image/<slug>).
- Fonts served: only Archivo/Inter/JetBrains Mono woff2, all 200 (see netreq-home-load.txt).
