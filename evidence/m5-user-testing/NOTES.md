# m5 user-testing validator — r1 notes (2026-10-20)

Scope: user-testing pass over M5 polish (a11y-motion, responsive sweep,
performance consistency) on the running Flask dev server (127.0.0.1:5199),
headless Chromium via agent-browser (CDP), 390x844 mobile emulation (plus a
spot check at the default desktop size). All interaction probes ran through
in-page `eval` scripts.

## Findings fixed in r1

### VAL-RSP-004b: sub-44px tap targets on footer and breadcrumb links
A full interactive-control audit on the product page at 390x844 found three
reachable links below the 44px tap-target law: site-footer links (36px min
height) and breadcrumb links (no min height, ~23px rendered).

Fix (CSS, src + rebuilt bundles):
- `.site-footer__links a`: min-height 36px → `var(--tap-target)`.
- `.breadcrumb a`: new `display:inline-flex; align-items:center;
  min-height: var(--tap-target)`.
Post-fix audit on `/product/rust-esp-lite` at 390: **zero** sub-44px
interactive controls remain. style.css rebuilt at 79.1 KB (budget ≤ 80KB).

### VAL-FAQ-001: FAQ answers never expand (engine-specific transition failure)
Clicking a FAQ question toggled `.open` and aria-expanded correctly, but the
answer stayed at 0px in this browser build (Chrome 148 / Electron 42 via
CDP). Root-caused: the stylesheet's `transition: grid-template-rows
var(--duration-normal) var(--ease-standard)` on `.faq-answer` never fires
transitionrun/start/end and the `1fr` track resolves to 0px when the class
flips; with `transition: none` the same element opens to 96.5px instantly.
Reproduced with clones/inline overrides to isolate it from the app markup.

Fix (script.js, belt-and-braces): a one-shot feature-detect probe animates a
detached grid element; if no transition event fires, the transition is
stripped from every `.faq-answer` so answers open instantly (content always
reachable). Reduced-motion users keep the instant-open path from the global
reduce block. Verified after deploy: open → 97px visible, aria-expanded=true,
second click closes to 0. Cache buster bumped to `script.js?v=19`.

## Verified working (no action)

- Mobile burger menu (390): 44x44 button, opens/closes, aria-expanded synced,
  7 links all ≥ 44px tall (48px) and inside the viewport, Escape closes and
  restores body scroll.
- Skip link is the first focusable, becomes visible on focus, target
  `#main-content` carries tabindex="-1".
- Images: 8/9 lazy-loaded, all with intrinsic dimensions; script v19 served.
- Reveal elements never stuck hidden at 390 (0 hidden in viewport).
- No horizontal overflow at 390 on /, /cheats, /status, /faq, /auth/login,
  /product/rust-esp-lite, /my-keys (via redirect), and admin pages.
- Header/footer chrome computed styles identical across all pages probed.
- Status board: sr-only role=status live region present, statusRefresh() runs
  clean, 8 rows, none clipped.
- FAQ search: live count announces ("1 match for refund" → "12 answers"),
  accordion toggling and aria-expanded correct after the fix.
- Login empty submit: 2 inline role=alert errors ("Username is required"),
  focus moved into the offending field.
- Catalogue: search `?q=rust` filters 7 → 3 cards, sort select present.
- Auth gate: /my-keys and /admin/* redirect anonymous users to login with
  `next`.
- Admin at 390 (logged in as demo_admin): no page overflow; the wide
  admin-table scrolls inside `.admin-main { overflow-x: auto }` (by design,
  page never overflows); shared confirm modal exists hidden until invoked.
- Reduced-motion emulation: reveals all visible, transitions clamped to
  150ms, no animation loops.
- Console/errors: no new console errors or failed resources observed during
  the sweep (aligns with the m5-performance-consistency network capture).

## Regression

- Full pytest suite: 416 passed (cache-buster expectation in
  test_auth_login.py updated 16 → 19 alongside the bumpy).
- CSS build clean: style.css 79.1 KB / admin.css 9.8 KB, both within budget.

## Evidence files

- `faq-open-390.png` (attempted; screenshot capture timed out on the CDP
  daemon intermittently on this host — documented quirk in earlier
  milestones; DOM computed-style captures above stand in per
  library/user-testing.md §7).
