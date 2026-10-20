# BEAZT Design System — Design Tokens

This document catalogs the CSS custom properties (design tokens) used by the
BEAZT "SIGNAL" design system. The source of truth is
`static/css/src/tokens.css`; the built bundles (`static/css/style.css`,
`static/css/admin.css`) are generated from it by `node scripts/build-css.mjs`
and mangle token names, so never hand-edit the built files or grep them for
token names — read the src instead.

## Overview

The design system uses a three-layer token architecture:

1. **Primitive tokens** — raw values (graphite neutrals, bone text ramp,
   signal amber, status hues)
2. **Semantic tokens** — purpose-based aliases (`--bg-*`, `--text-*`,
   `--accent*`, `--status-*`, `--border-*`)
3. **Component tokens** — sizing/shape shared by the component library

Pages and components should only reference semantic or component tokens.

### Contrast law (pytest-enforced)

Every token used for meaningful text reaches ≥ 4.5:1 on every surface it is
paired with. `--text-faint` is decorative only (dividers, disabled hints) and
never carries information. The ratios are computed from the token values in
`tests/test_design_system.py` — adjust values there and in `tokens.css`
together.

## Foundation Colors

Graphite neutrals with no blue cast — calm, instrument-grade surfaces.

| Token | Value | Usage |
|-------|-------|-------|
| `--graphite-950` | `#0B0D10` | Deepest surface (page edges, insets, overlay) |
| `--graphite-900` | `#101318` | Page background |
| `--graphite-850` | `#161A20` | Cards, panels |
| `--graphite-800` | `#1C2128` | Interactive surfaces |
| `--graphite-750` | `#232931` | Hover surfaces |
| `--graphite-700` | `#2A313A` | Strongest surface step |

Semantic surfaces:

| Token | Resolves to | Usage |
|-------|-------------|-------|
| `--bg-void` | `--graphite-950` | Page edges, inset fields, overlay base |
| `--bg-base` | `--graphite-900` | Primary page background |
| `--bg-elevated` | `--graphite-850` | Cards, panels |
| `--bg-surface` | `--graphite-800` | Secondary buttons, hovers |
| `--bg-surface-hover` | `--graphite-750` | Hover state of surface elements |
| `--bg-inset` | `--graphite-950` | Inputs, code blocks |
| `--bg-overlay` | `rgba(11, 13, 16, 0.78)` | Modal backdrop (solid, no blur) |

## Text Colors

Warm bone ramp on graphite.

| Token | Value | Usage |
|-------|-------|-------|
| `--text-primary` | `#F2F0EA` (`--bone-50`) | Headings, primary text |
| `--text-secondary` | `#B4BAC4` (`--bone-300`) | Body copy, secondary labels |
| `--text-muted` | `#8E96A3` (`--bone-500`) | Captions, hints (≥ 4.5:1 on base and elevated) |
| `--text-faint` | `#5C6470` (`--bone-600`) | **Decorative only** — dividers, disabled hints |
| `--grey-400` | `#98A0AC` | Feeds `--status-unknown` |

## Accent Colors

One hot signal amber, reserved for primary CTAs, prices, links and active
nav/selection. Never for glows, decorative washes, or more than one prominent
element per viewport section. Status colors are for STATUS ONLY.

| Token | Value | Usage |
|-------|-------|-------|
| `--accent` | `#E8A33D` (`--amber-500`) | Primary accent |
| `--accent-hover` | `#F2B558` (`--amber-400`) | Hover state |
| `--accent-pressed` | `#CE8B2D` (`--amber-600`) | Pressed/active state |
| `--on-accent` | `#171310` (`--amber-ink`) | Text on amber (≥ 4.5:1) |
| `--accent-tint` | `rgba(232, 163, 61, 0.12)` | Selected/hover washes |
| `--accent-border` | `rgba(232, 163, 61, 0.40)` | Amber border on selected/focused states |
| `--link` | `--accent` | Link color |
| `--link-hover` | `--accent-hover` | Link hover |

## Status Colors

Semantic status family — always paired with a dot + text label. Feedback
aliases (`--success`, `--info`, `--danger`, `--warning` and their `-bg` /
`-border` pairs) map onto the same hues for forms, toasts and badges.

| Token | Value | Meaning |
|-------|-------|---------|
| `--status-undetected` | `#46D08C` | Undetected / success |
| `--status-undetected-bg` | `rgba(70, 208, 140, 0.10)` | Pill background |
| `--status-undetected-border` | `rgba(70, 208, 140, 0.28)` | Pill border |
| `--status-updating` | `#5FA8E8` | Updating / info |
| `--status-updating-bg` | `rgba(95, 168, 232, 0.10)` | Pill background |
| `--status-updating-border` | `rgba(95, 168, 232, 0.28)` | Pill border |
| `--status-detected` | `#F0575F` | Detected / danger |
| `--status-detected-bg` | `rgba(240, 87, 95, 0.10)` | Pill background |
| `--status-detected-border` | `rgba(240, 87, 95, 0.28)` | Pill border |
| `--status-risky` | `#F59A4A` | Risky / warning |
| `--status-risky-bg` | `rgba(245, 154, 74, 0.10)` | Pill background |
| `--status-risky-border` | `rgba(245, 154, 74, 0.28)` | Pill border |
| `--status-unknown` | `#98A0AC` | Unknown |
| `--status-unknown-bg` | `rgba(152, 160, 172, 0.10)` | Pill background |
| `--status-unknown-border` | `rgba(152, 160, 172, 0.28)` | Pill border |

Pill text on tint backgrounds is pytest-enforced at ≥ 4.5:1 (see
`partials/status_pill.html` for the component).

## Border Tokens

Hairline borders separate surfaces; the amber border appears only on
selected/focused states.

| Token | Value | Usage |
|-------|-------|-------|
| `--border-subtle` | `rgba(255, 255, 255, 0.07)` | Card borders, quiet separation |
| `--border-default` | `rgba(255, 255, 255, 0.11)` | Standard borders, inputs |
| `--border-strong` | `rgba(255, 255, 255, 0.17)` | Hover borders, emphasis |
| `--accent-border` | `rgba(232, 163, 61, 0.40)` | Selected/focused accent border |

## Shadow Tokens

Neutral elevation only — no coloured shadows, no glows.

| Token | Usage |
|-------|-------|
| `--shadow-xs` | Minimal elevation |
| `--shadow-sm` | Small elements |
| `--shadow-md` | Default cards |
| `--shadow-lg` | Large cards, popovers |
| `--shadow-xl` | Floating elements |
| `--shadow-2xl` | Modals, overlays |

## Typography

All fonts are self-hosted woff2 (SIL OFL) in `static/fonts/`. No external
font requests, ever. Display roles set the width axis of the Archivo variable
font via `font-stretch`; numbers that stack or compare use the mono stack,
which carries `font-variant-numeric: tabular-nums` by default (`base.css`).

| Token | Value | Usage |
|-------|-------|-------|
| `--font-display` | `"Archivo", "Inter", system-ui, …` | Headings, display, eyebrows |
| `--font-body` | `"Inter", system-ui, …` | Body text |
| `--font-mono` | `"JetBrains Mono", ui-monospace, …` | Keys, prices, timestamps, table numerics |
| `--font-stretch-display` | `115%` | Headings / hero (Archivo width axis) |
| `--font-stretch-eyebrow` | `120%` | Eyebrows, micro-labels |
| `--font-weight-display` | `640` | Display weight (variable axis) |

### Font Sizes

| Token | Value | Rem | Usage |
|-------|-------|-----|-------|
| `--text-xs` | `0.75rem` | 12px | Captions, badges |
| `--text-sm` | `0.875rem` | 14px | Small text, buttons |
| `--text-base` | `1rem` | 16px | Body text |
| `--text-lg` | `1.125rem` | 18px | Large body |
| `--text-xl` | `1.25rem` | 20px | Small headings |
| `--text-2xl` | `1.5rem` | 24px | Section headings |
| `--text-3xl` | `1.875rem` | 30px | Page headings |
| `--text-4xl` | `2.25rem` | 36px | Large headings |
| `--text-5xl` | `3rem` | 48px | Hero numerals |
| `--text-display` | `clamp(2.5rem, 1.5rem + 4vw, 3.75rem)` | — | Hero display |

### Line Heights and Tracking

| Token | Value |
|-------|-------|
| `--leading-none` | `1` |
| `--leading-tight` | `1.15` (headings) |
| `--leading-snug` | `1.35` |
| `--leading-normal` | `1.5` |
| `--leading-relaxed` | `1.65` (body) |
| `--tracking-display` | `-0.01em` |
| `--tracking-caps` | `0.08em` (uppercase micro-labels) |

### Font Weights

| Token | Value | Usage |
|-------|-------|-------|
| `--font-normal` | `400` | Body |
| `--font-medium` | `500` | Emphasis |
| `--font-semibold` | `600` | Buttons, labels |

## Spacing Tokens

4px base unit system.

| Token | Value | Pixels |
|-------|-------|--------|
| `--space-1` | `0.25rem` | 4px |
| `--space-2` | `0.5rem` | 8px |
| `--space-3` | `0.75rem` | 12px |
| `--space-4` | `1rem` | 16px |
| `--space-5` | `1.25rem` | 20px |
| `--space-6` | `1.5rem` | 24px |
| `--space-7` | `1.75rem` | 28px |
| `--space-8` | `2rem` | 32px |
| `--space-9` | `2.25rem` | 36px |
| `--space-10` | `2.5rem` | 40px |
| `--space-12` | `3rem` | 48px |
| `--space-16` | `4rem` | 64px |
| `--space-20` | `5rem` | 80px |
| `--space-24` | `6rem` | 96px |

Section rhythm: 4rem desktop / 3rem mobile.

## Border Radius Tokens

One radius per component family — no mixing.

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-xs` | `4px` | Tags |
| `--radius-sm` | `6px` | Small controls |
| `--radius-md` | `8px` | Inputs, buttons |
| `--radius-lg` | `12px` | Cards |
| `--radius-xl` | `16px` | Modals |
| `--radius-2xl` | `20px` | Hero cards |
| `--radius-full` | `9999px` | Pills, badges, avatars |

## Transition Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--duration-fast` | `150ms` | Hover/state changes |
| `--duration-normal` | `250ms` | State change, reveals |
| `--duration-slow` | `400ms` | Reveals (max) |
| `--ease-standard` | `cubic-bezier(0.2, 0, 0.2, 1)` | All transitions (`--ease-smooth` / `--ease-out` alias it) |
| `--reveal-distance` | `12px` | Reveal translate distance |

Reveals: 250ms opacity + 12px translateY with a 60ms stagger, gated on
`html.js`. One signature motion exists sitewide: the 700ms status-pill sweep
on `/status` data refresh. Everything decorative is disabled under
`prefers-reduced-motion: reduce` (override in `base.css`) — only ≤ 150ms
color/opacity transitions remain.

## Z-Index Scale

| Token | Value | Usage |
|-------|-------|-------|
| `--z-base` | `0` | Default stacking |
| `--z-elevated` | `10` | Slight elevation |
| `--z-sticky` | `100` | Sticky header |
| `--z-overlay` | `400` | Backdrops |
| `--z-modal` | `500` | Modals, dialogs |
| `--z-toast` | `600` | Toast notifications |

## Focus Tokens

| Token | Value |
|-------|-------|
| `--focus-ring-color` | `var(--accent)` |
| `--focus-ring-width` | `2px` |
| `--focus-ring-offset` | `2px` |
| `--focus-ring` | `0 0 0 var(--focus-ring-offset) var(--bg-base), 0 0 0 calc(var(--focus-ring-offset) + var(--focus-ring-width)) var(--focus-ring-color)` |

## Layout Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--container-max` | `1200px` | Standard container |
| `--container-sm` | `880px` | Narrow container |
| `--container-lg` | `1360px` | Wide container |
| `--container-padding` | `var(--space-6)` (24px; 16px under 640px) | Container side padding |
| `--header-height` | `64px` | Sticky header |

## Component Tokens

### Controls

| Token | Value |
|-------|-------|
| `--control-height` | `44px` |
| `--control-height-sm` | `36px` |
| `--control-height-lg` | `52px` |
| `--tap-target` | `44px` |

### Button Tokens

| Token | Value |
|-------|-------|
| `--button-radius` | `var(--radius-md)` |
| `--button-font-size` | `var(--text-sm)` |
| `--button-font-weight` | `var(--font-semibold)` |
| `--button-padding-x` | `var(--space-5)` |

### Input Tokens

| Token | Value |
|-------|-------|
| `--input-bg` | `var(--bg-inset)` |
| `--input-border` | `var(--border-default)` |
| `--input-border-hover` | `var(--border-strong)` |
| `--input-radius` | `var(--radius-md)` |
| `--input-padding-x` | `var(--space-4)` |

### Card Tokens

| Token | Value |
|-------|-------|
| `--card-bg` | `var(--bg-elevated)` |
| `--card-border` | `var(--border-subtle)` |
| `--card-radius` | `var(--radius-lg)` |
| `--card-padding` | `var(--space-6)` |
| `--card-padding-sm` | `var(--space-4)` |

### Badge Tokens

| Token | Value |
|-------|-------|
| `--badge-radius` | `var(--radius-full)` |
| `--opacity-disabled` | `0.5` |

## Usage Examples

### Primary Button

```css
.btn--primary {
  background: var(--accent);
  color: var(--on-accent);
  border-radius: var(--button-radius);
  min-height: var(--control-height);
  font-weight: var(--button-font-weight);
  transition: background-color var(--duration-fast) var(--ease-standard);
}

.btn--primary:hover {
  background: var(--accent-hover);
}
```

One button animation: background/border color 150ms — no scale on primary.

### Card

```css
.card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: var(--card-radius);
  padding: var(--card-padding);
  box-shadow: var(--shadow-xs);
  transition: translate var(--duration-fast) var(--ease-standard),
              border-color var(--duration-fast) var(--ease-standard);
}

.card:hover {
  translate: 0 -2px;
  border-color: var(--border-strong);
}
```

### Status Pill

```css
.pill--undetected {
  background: var(--status-undetected-bg);
  color: var(--status-undetected);
  border: 1px solid var(--status-undetected-border);
  border-radius: var(--badge-radius);
}
```

The pill component lives in `templates/partials/status_pill.html` — the one
status vocabulary sitewide (Undetected / Updating / Risky / Detected / Down).
Availability ("In stock" / "Sold out" / "Private build") is a separate neutral
badge, never merged into the pill.

## Maintenance Notes

1. **Tokens first.** Pages and components reference semantic/component
   tokens only — never raw hex values from the ramp.
2. **Contrast is test-enforced.** If you change a text token, update the
   expected values in `tests/test_design_system.py` in the same change.
3. **Build after every CSS change.** `node scripts/build-css.mjs` regenerates
   `style.css` / `admin.css` and bumps the `style.css` cache-buster; bump the
   `script.js?v=N` cache-buster manually in `templates/base.html` and
   `templates/admin/base.html` when the JS changes.
4. **Never hand-edit built bundles.** They are minified and token-mangled.
5. **Touch targets.** Interactive controls meet the 44px minimum
   (`--tap-target`).
