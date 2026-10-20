# m3-content-pages — verification notes

Feature: FAQ / loader guide / legal pages / 404 on SIGNAL with reconciled copy
(VAL-CON-001..004, VAL-CROSS-005).

## What changed

- `templates/partials/copy.html` (NEW): single canonical delivery promise
  ("Your key appears in your account the moment payment is confirmed — usually
  within seconds.") adopted by index, product, keys, feedback, faq, loader,
  site_footer and the base meta description.
- `templates/faq.html`: DB-derived game answer (3 games, from the catalogue
  cards — never goes stale), canonical promise in the delivery answer, NEW
  answers #11 (status label meanings) and #12 (requirements); deep-link ids
  faq-answer-1..10 unchanged, 11/12 appended. "Operator" prose retired.
- `routes/main.py faq()`: +2 lines, passes `games` (group_games(_all_cards()))
  so the FAQ copy traces to real data.
- `templates/loader.html`: rebuilt — zero inline `style=`/`<style>`, canonical
  promise, game-aware step 6 ("Launch <game>"), unconfigured loader URLs
  degrade to the My Keys card (no dead download links), "Instant key delivery"
  badge reworded to "Key delivery in seconds".
- `templates/privacy.html`: false "Google Fonts (Google CDN)" third-party
  claim replaced with the self-hosted-fonts fact.
- `templates/404.html`: rebuilt without the inline stylesheet; recovery links
  now cover home + catalogue + status (primary) and FAQ/Setup/Reviews/My Keys
  (chips); glow + gradient-text removed.
- CSS: FAQ / Loader guide / Legal / 404 sections ported from `legacy.css` into
  `static/css/src/site.css` on v2 tokens (glows, gradient hairline, dead
  `.faq-item-number`/`.faq-answer-more` rules dropped). legacy.css went from
  1970 to 889 lines; brace-balanced; zero faq-/loader-/legal-/nf- selectors
  left in it.

## Verification

- pytest: 23 new tests in `tests/test_content_pages.py`; full suite 366 passed.
- CSS build clean (`style.css` 116.2 KB at ?v=40; the ≤80 KB budget is
  m3-legacy-deletion's remaining purge, not this feature's).
- Browser (agent-browser, session 29924e37ced9, headless):
  - Screenshots before/after at 1440×900 and 390×844 for /faq, /loader,
    /loader/rust-esp-lite, /terms-of-service, /privacy, 404 — all 24 files
    hash-unique (Get-FileHash MD5, listed in handoff).
  - DOM probes via `eval --stdin` (click/find commands hang on this build —
    documented in library/user-testing.md 3p):
    - 404: actions = Back to home → /, Browse the catalogue → /cheats,
      Check status → /status; chips → /faq /loader /feedback /my-keys.
    - FAQ: accordion opens (faq-item.open, answer height 71px after
      transition), search "refund" → 1 match with live count, clear → 12
      restored; promise + "BEAZT covers 3 games" visible.
    - Loader (generic): 0 empty hrefs, 0 inline style attrs, promise in info
      callout, no Rust-only claim, 10 My Keys links.
    - Loader (product rust-esp-lite): step 6 "Launch Rust and verify the
      overlay", badges Undetected / Windows 10-11 / Key delivery in seconds,
      product notes render, guide marked aria-current.
    - Legal (terms + privacy): 10 TOC links, 10 sections, 4 related cards,
      sticky TOC (position: sticky), "Last updated: June 2026".
    - My Keys (logged in as demo_buyer): promise present, 3 key cards,
      3 order-history rows.
  - Console sweep: clean on /, /faq, /loader, /loader/rust-esp-lite,
    /terms-of-service, /privacy, 404, /feedback.
  - 404 computed styles: nf-code = JetBrains Mono, rgb(242,240,234)
    (--text-primary), filter: none (glow gone); chip bg rgb(22,26,32)
    (--bg-elevated), radius 9999px; bundle style.css?v=40.

## Known limitations

- agent-browser `click`/`find … click` hang in this session — interactions
  were driven via `eval --stdin` native-DOM calls instead (pytest + DOM probes
  carry the behavioral evidence).
- Screenshot visual inspection not possible (image-blind session); DOM
  computed-style captures stand in per library/user-testing.md §7.
