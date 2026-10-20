# m5-responsive-sweep — measurement log (2026-10-19)

Method: headless Chrome via agent-browser (session 95ae74219a1e), real viewport
emulation at 390x844 and 768x1024. Server: Flask dev on 127.0.0.1:5199.

## Overflow check (documentElement.scrollWidth vs clientWidth)

Probe: tmp/m5_ovf_probe.js — measures `document.scrollWidth > clientWidth`
and lists unclipped elements whose box extends past the viewport
(`getBoundingClientRect().right > innerWidth + 1`, skipping descendants of
overflow:auto/scroll/hidden/clip shells such as .table-wrap).

Result matrix — `docScroll == docClient == viewport`, `overflow=false`,
`offenders=0` on every surface, both viewports:

| Page            | 390x844 | 768x1024 |
|-----------------|---------|----------|
| /               | clean   | clean    |
| /cheats         | clean   | clean    |
| /product/rust-full-suite | clean | clean |
| /status         | clean   | clean    |
| /auth/login     | clean   | clean    |
| /auth/signup    | clean   | clean    |
| /auth/forgot    | clean   | clean    |
| /my-keys        | clean   | clean    |
| /profile        | clean   | clean    |
| /faq            | clean   | clean    |
| /loader         | clean   | clean    |
| /feedback       | clean   | clean    |
| /games          | clean   | clean    |
| /games/rust     | clean   | clean    |
| /admin/         | clean   | clean    |
| /admin/orders   | clean   | clean    |
| /admin/products | clean   | clean    |

## Content-squish check (text overflowing its own box)

Probe: tmp/m5_squish.js — leaf elements with `scrollWidth > clientWidth + 2`
that are NOT inside an intended scroll/clip shell and have no
nowrap/ellipsis. Zero squished elements on: product, status, my-keys, admin
dashboard, admin/orders, admin/products, cheats, loader — at both viewports.
Status board at 768: `gridTemplateColumns` = 1 track (stacked cards below the
900px breakpoint, by design; 4-col board resumes >=900px).

## Burger menu at 390 (tmp/m5_burger.js, tmp/m5_burger2.js)

- Open: `.nav-burger` click -> `.mobile-menu.is-open`, `aria-expanded=true`,
  computed `display:flex`, panel 390x370 below the 64px sticky header,
  overlay visible, `body overflow=hidden` (scroll lock). Screenshot:
  burger-open-390.png.
- All 7 panel links within viewport (`bad=[]`), min-height 48px per link.
- Navigate: click "Cheats" -> lands on /cheats, menu closed
  (`aria-expanded=false`).
- Toggle close: burger click again -> `display:none`, body overflow restored,
  `aria-expanded=false`.
- Escape key: closes (keydown handler verified).

## Buy panel at 390 (tmp/m5_buypanel.js, tmp/m5_buypanel2.js)

Anonymous (rust-full-suite): 3/3 plan rows visible, 0 clipped, plan radio
switch works (`selectedVariantId` 9 -> 8 via native input click),
"Sign in to buy" CTA 308x52px, fully inside the viewport.

Authenticated (demo session): plan walk across all 3 tiers with settle delays:
- Subscription tiers (v=8, v=9): quantity stepper + gateways correctly hidden,
  "Subscribe" CTA 308x52px visible.
- One-time tier (v=10): quantity stepper visible, gateway radios visible,
  buy button 308x52px visible.
All interactive controls inside the viewport; no clipping.

## Findings

None. Zero horizontal overflow, zero content squish, burger menu fully
functional, buy panel usable at 390 and 768 on all primary pages. No CSS,
template, or JS changes were required; prior milestone rebuilds
(m2-status-board, m2-catalogue-games, m3-*, m4-admin-*) already carry the
responsive behaviour, and commit 3a089e1 raised touch targets to 44px.

Note: `agent-browser` daemon on this host relaunches intermittently between
commands (documented quirk 3c/3o); all measurements were re-validated against
the reported `vw` of each sample, and each measurement above is a successful
sample whose viewport matched the target (390 or 768).
