# m5 scrutiny validator — r1 notes (2026-10-20)

Scope: scrutiny review of the M5 polish surface (a11y-motion, responsive
sweep, performance consistency) — code, CSS sources, templates, JS.

## Method

- Full pytest suite: 416 passed (includes the m5-a11y-motion design-system
  tests: reduced-motion gating of the toast dismiss slide, 44px tap-target
  token consumption, lazy aria-live toast region).
- `node scripts/build-css.mjs` re-run: style.css 79.0 KB (budget ≤ 80KB) and
  admin.css 9.8 KB (budget ≤ 12KB) both report "up to date" — no drift between
  src and built bundles.
- Manual code review of the M5-relevant layers:
  - `static/css/src/base.css` — global `prefers-reduced-motion: reduce`
    block kills animations/transitions/scroll-behavior and force-shows
    reveals; reveals are hidden only under `.js` + no-preference, so content
    can never get stuck invisible.
  - `static/css/src/site.css:1972` — status sweep shimmer additionally gated.
  - `static/js/script.js` — reveal system skips scroll-driven animation under
    reduced motion; scroll/resize listeners use `{ passive: true }`, rAF
    throttling on the header effect, setTimeout throttle (not rAF) for the
    reveal check so it works when frames are throttled.
  - Templates — `lang="en"`, skip link → `#main-content`, burger carries
    aria-expanded/aria-controls, live regions: flash container
    aria-live=polite, status board sr-only role=status, product gallery
    announcement, inline form errors role=alert.
  - Performance: single stylesheet, deferred script, vendored Alpine/Lucide
    injected post-load, only the display font preloaded, below-fold images
    lazy with intrinsic dimensions, product main image fetchpriority=high;
    no `will-change` anywhere in the CSS sources; zero inline styles/event
    handlers in admin templates (pytest-enforced).

## Finding fixed in r1

**VAL-DS-005 (m5 scrutiny r1): JS reduced-motion state went stale.**
`script.js` captured `matchMedia("(prefers-reduced-motion: reduce)").matches`
as a boolean at load. If the user enabled reduced motion after the page had
loaded (Settings → accessibility), the CSS correctly stopped all motion but
the JS scroll-driven reveal kept running (adding .visible / transitioning
transforms) until reload.

Fix: keep the live MediaQueryList and subscribe to `change`; `reducedMotion`
now tracks the current preference for the session. The one-shot boolean read
remains as the initial value, so no behaviour changes for the common case.

- Verified: `node --check static/js/script.js` clean; design-system tests
  98 passed after the change.
- Cache busters: script.js bumped v16 → v17 in `templates/base.html` and
  `templates/admin/base.html` (style/admin css busters unchanged — no CSS
  edits).

## Other checks (no action needed)

- Escape-close on the mobile menu returns focus to the burger; link clicks
  close the menu; body scroll lock is restored on every close path.
- Status board stacked cards below 900px is the designed breakpoint
  behaviour, confirmed in the responsive sweep measurement log.
- No legacy CSS references: faq-/loader-/legal-/nf- selectors stay out of
  the sources (m3-legacy-deletion tests still enforce this).
- No console errors / 4xx-5xx resources in the performance-consistency
  sweep across home, cheats, product, status, auth, my-keys (desktop +
  mobile viewports).
