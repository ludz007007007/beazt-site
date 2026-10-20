# BEAZT Design System — SIGNAL

Source: the approved "SIGNAL" design direction — an instrument-grade
storefront for risk decisions. The site reads like mission-control telemetry:
calm graphite surfaces, disciplined grids, warm bone text, and one hot amber
signal reserved for actions and money. The honest live-status data IS the
design concept.

The token layer documented here is implemented in `static/css/src/tokens.css`
(value tables in `DESIGN_TOKENS.md`); the component layer lives in
`static/css/src/components.css` (storefront) and `static/css/src/admin.css`
(admin). This file describes how the system is meant to be used.

## Brand Pillars

- **Mood:** instrument-grade precision — calm, precise, premium. Never loud,
  never neon, never generic.
- **Experience goals:** instant clarity for risk decisions, honest data as the
  hero, one restrained motion system.
- **Avoid (hard rules):** neon glow, glassmorphism, arbitrary gradients,
  decorative particles/grid overlays, purple/blue accent (competitor cliché),
  repetitive identical card rows without hierarchy variation, dark patterns in
  UI or copy.

## Layout & Spacing

- 4px grid via the `--space-1..24` scale.
- Containers: 1200px standard (`--container-max`), 880px narrow, 1360px wide;
  24px side padding (16px under 640px).
- Section rhythm: 4rem desktop / 3rem mobile. Section pattern: eyebrow
  (optional index number 01/02/03) + display heading + lede.
- Header: 64px sticky. Footer: 4-col (Shop / Help / Legal / Brand), facts
  strip (DB-backed facts only), legal line.

## Color

Graphite surface ramp (`#0B0D10 → #2A313A`), warm bone text ramp
(`#F2F0EA → #5C6470`), one signal amber (`#E8A33D`) and a status family
(emerald / blue / red / orange / grey). Full value tables: `DESIGN_TOKENS.md`.

- Amber is reserved for: primary CTAs, prices, links, active nav/selection.
  Never for decorative fills, glows, or more than one prominent element per
  viewport section.
- Status colors are for STATUS ONLY — never accents. The status vocabulary is
  a single taxonomy: Undetected / Updating / Risky / Detected / Down.
  Availability ("In stock" / "Sold out" / "Private build") is a separate
  neutral badge, never blended into the pill.
- Hairline borders separate surfaces (`--border-subtle/default/strong`); the
  amber border appears only on selected/focused states.

## Typography

All self-hosted woff2 (SIL OFL) in `static/fonts/`. No external font requests.

- **Display:** Archivo variable (wght 100–900, wdth 62–125). Headings and
  hero use `font-stretch: 115%`, weight 640, `letter-spacing: -0.01em`;
  eyebrows/micro-labels use `font-stretch: 120%`, weight 600, uppercase,
  `letter-spacing: 0.08em`, 12px.
- **Body:** Inter variable — 400 body / 500 emphasis / 600 buttons + labels.
- **Mono:** JetBrains Mono 500 — license keys, prices, timestamps, table
  numerics. Always `font-variant-numeric: tabular-nums` where numbers stack
  or compare (the mono stack carries it by default; `.tabular` utility
  elsewhere).
- Scale (px): 12 · 14 · 16 · 18 · 20 · 24 · 30 · 36 · 48, plus the hero
  `clamp(2.5rem, 1.5rem + 4vw, 3.75rem)` display size.
- Loading: only the display font is preloaded in `base.html`; everything else
  uses `font-display: swap`.

## Shape & Elevation

- Radius: inputs/buttons 8px (`--radius-md`), cards 12px (`--radius-lg`),
  pills/badges full, modal 16px. ONE radius per component family.
- Shadows: neutral elevation only (`--shadow-xs` … `--shadow-2xl`). No
  coloured shadows, no glows.
- Hairline borders separate surfaces; amber border only on selected/focused.

## Components

All shared components live in `static/css/src/components.css` and
`templates/partials/`. Consume them; never re-invent.

- **Buttons:** primary (amber bg, ink text) / secondary (surface bg, border) /
  ghost / danger / link. Sizes: sm 36, md 44, lg 52. Loading state: spinner +
  `aria-busy`, label preserved. One animation: background/border color 150ms —
  no scale on primary.
- **Hover language (one system):** cards lift −2px + border brightens +
  surface lightens; buttons shift one bg step; list rows brighten bg. No
  translateX rows, no shine sweeps, no shadow growth on cards.
- **Status pill** (`partials/status_pill.html`): dot + label, one taxonomy
  everywhere. Pill text ≥ 4.5:1 on its tint background (pytest-enforced).
- **Cards:** product card = 16:9 media (typographic cover fallback) + content
  (status pill, name, meta, from-price footer, single stretched link). Game
  card = cover + count + ratio line.
- **Forms:** `.form-group/.form-label/.form-input/.form-select` + hint +
  inline error (`role=alert`, `aria-invalid`, `aria-describedby`). Validate on
  blur + submit; focus first error. 44px inputs. The only form markup in the
  codebase — auth, profile, admin, review form, contact surfaces.
- **Toasts** (`partials/flash_toasts.html` + `window.BEAZT.toast`): top-right
  under header; success auto-dismisses after 4.2s; errors persist with a
  dismiss control; `aria-live=polite`.
- **Modal** (confirm dialog partial): solid overlay `--bg-void/0.78` (no
  blur), 16px radius, focus trap, Escape closes, backdrop click closes —
  except destructive confirms, where backdrop click does NOT close. Replaces
  all `alert()`/`confirm()` usage.
- **Tabs:** ARIA pattern — roving tabindex, Arrow/Home/End keys,
  `aria-selected`, panels `tabindex=0`. Static `hidden` on panels is the
  no-JS fallback; visibility is toggled via `:hidden` Alpine bindings (a
  static attribute alone cannot be removed by class toggling — `base.css`
  enforces `[hidden]{display:none!important}`).
- **Tables/boards:** `.table-wrap` scroll shell on desktop; stacked cards
  under 640–900px that NEVER drop fields. Header rows use `--text-secondary`
  12px caps.
- **Empty states:** one partial — icon, title, one sentence, one action.
  Never a bare "No results."
- **Skeletons:** only where content is genuinely async. Server-rendered
  content never hides behind `x-cloak` (My Keys renders without JS).
- **Pricing panel:** plan ladder rows (radios) with label, explicit
  `One-time · N days` or `Recurring` tag, price in mono, per-day cost
  secondary line, best-value marker on the best per-day plan, gateway row with
  minimums up front (unconfigured → disabled + reason), quantity stepper with
  "N keys per order" explanation, total in the buy button label.

## Motion

- State changes 150ms `--ease-standard`. Reveals 250ms (opacity + 12px
  translateY, 60ms stagger, `html.js` gate). Hover lifts 150ms.
- ONE signature: the **status sweep** — on `/status` data refresh, a 700ms
  amber-tinted sheen passes through updated rows. Nothing else like it
  anywhere.
- `prefers-reduced-motion: reduce` → no reveals/sweeps/lifts; only ≤ 150ms
  color/opacity transitions. The global override lives in `base.css`.

## Art Direction

- **Typographic cover system** (deterministic, per game): graphite field,
  game wordmark set in Archivo expanded caps, status-colour accent bar,
  subtle per-game geometric motif derived from a hash of the game slug
  (always < 8% visual weight). Implemented server-side via
  `/cheat-image/<slug>` and `/game-image/<game>`. 16:9 with intrinsic sizes
  in markup — never stretched or raster-blown-up, always crisp.
- Real `gallery_images` render when present; the cover is the guaranteed
  fallback for every product.
- OG images: per-product cover on product pages; the default brand card
  (`static/images/og-default.png`, regenerated by `scripts/make_og_card.py`)
  everywhere else.

## Iconography

- Lucide SVG set, vendored in `static/js/vendor/`, injected after window load
  (`data-lucide` hydrate). Use `.icon` utility classes for sizing; `icon-sm`
  for inline text icons. Decorative icons carry `aria-hidden="true"`.

## Accessibility Checklist

- Contrast ≥ 4.5:1 for all meaningful text (pytest-computed from tokens);
  `--text-faint` never carries information.
- Hit areas ≥ 44px (`--tap-target`), visible focus ring (`--focus-ring`),
  `cursor: pointer`.
- Full keyboard paths on money journeys; real keystrokes for tabs/steppers
  (roving tabindex, Arrow keys).
- `aria-label`s on icon-only controls; `prefers-reduced-motion` guarded
  everywhere; skip link to `#main-content`.
- Status changes announced via polite live regions (`role=status`).

## Copy Voice

- Plain, specific, calm confidence. British English, £ pricing. Say what
  things are, name real dates, link real data.
- Delivery promise (single canonical wording, `partials/copy.html`):
  "Your key appears in your account the moment payment is confirmed — usually
  within seconds."
- CTA labels: primary verb + object ("Browse cheats", "Check status",
  "Get <game>", "Buy — £24.99", "Create account").
- Honesty rules (binding): no fabricated stock counts, live-purchase toasts,
  fake urgency, invented testimonials/counters, or unverifiable superlatives.
  Every trust claim traces to real DB data; "Updated" labels come from the
  database, never render time.

## CSS Architecture & Build

```
static/css/src/
  tokens.css        # token layers (source of truth)
  base.css          # reset, typography, focus, reduced-motion override
  site.css          # shell, header, footer, page-scoped rules (/* Page: X */)
  components.css    # storefront component library
  admin.css         # admin component library
node scripts/build-css.mjs   # → static/css/style.css + admin.css (minified)
```

- Edit src only; never hand-edit the built bundles (they are minified and
  token-mangled). Run the build after every CSS change.
- Budgets (pytest-enforced): `style.css` ≤ 80KB minified, `admin.css` ≤ 12KB.
- No inline `<style>` blocks, no inline `style=` on controls, no inline
  `on*=` handlers (Alpine attributes are fine; the product-page checkout wire
  block is the pinned exception).
- Cache-busters: the build bumps `style.css?v=N` in both base templates;
  bump `script.js?v=N` manually when `static/js/script.js` changes.
