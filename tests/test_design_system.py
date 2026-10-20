"""Design system foundation: built CSS palette, self-hosted fonts, site shell."""

import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_DIR = os.path.join(ROOT, "static", "css")
TOKENS_PATH = os.path.join(CSS_DIR, "src", "tokens.css")

AMBER = ["#E8A33D", "#F2B558", "#CE8B2D", "#171310"]
GRAPHITE = ["#0B0D10", "#101318", "#161A20", "#1C2128", "#232931"]
BONE = ["#F2F0EA", "#B4BAC4", "#8E96A3"]
STATUS = ["#46D08C", "#5FA8E8", "#F0575F", "#F59A4A", "#98A0AC"]


# ---------------------------------------------------------------------------
# Token parsing + WCAG contrast math (tokens.css is the single palette source)
# ---------------------------------------------------------------------------

def _parse_tokens():
    """Read custom properties from tokens.css and resolve var() chains."""
    src = open(TOKENS_PATH, encoding="utf-8").read()
    raw = {name: value.strip() for name, value in
           re.findall(r"^\s*(--[\w-]+)\s*:\s*([^;]+);", src, re.M)}

    def resolve(name, seen=()):
        assert name not in seen, f"circular token reference at {name}"
        value = raw[name]
        m = re.fullmatch(r"var\((--[\w-]+)\)", value)
        return resolve(m.group(1), seen + (name,)) if m else value

    return {name: resolve(name) for name in raw}


def _as_rgba(value):
    """'#RRGGBB' or 'rgba(r, g, b, a)' -> (r, g, b, a) floats."""
    value = value.strip()
    m = re.fullmatch(r"#[0-9a-fA-F]{6}", value)
    if m:
        return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16), 1.0)
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)", value)
    assert m, f"unsupported colour token value: {value!r}"
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)),
            float(m.group(4)) if m.group(4) else 1.0)


def _relative_luminance(rgba):
    def channel(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgba[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(fg_value, bg_value):
    """WCAG 2.1 contrast ratio between two token values."""
    fg, bg = _as_rgba(fg_value), _as_rgba(bg_value)
    if bg[3] < 1:
        raise AssertionError("background must be opaque; composite tints first")
    l1, l2 = _relative_luminance(fg), _relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _composite(tint_value, base_value):
    """Flatten a translucent token over an opaque surface -> '#RRGGBB'."""
    r, g, b, a = _as_rgba(tint_value)
    br, bg, bb = _as_rgba(base_value)[:3]
    return "#{:02X}{:02X}{:02X}".format(
        round(a * r + (1 - a) * br), round(a * g + (1 - a) * bg), round(a * b + (1 - a) * bb))



def _css(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, path
    return resp.get_data(as_text=True)


def _all_css_files():
    for dirpath, _dirs, files in os.walk(CSS_DIR):
        for name in files:
            if name.endswith(".css"):
                yield os.path.join(dirpath, name)


@pytest.mark.parametrize("hex_value", AMBER + GRAPHITE + BONE + STATUS)
def test_served_css_defines_palette(client, hex_value):
    css = _css(client, "/static/css/style.css").upper()
    assert hex_value in css


# --- WCAG contrast: every meaningful-text token pair >= 4.5:1 ---------------

SURFACES = ["--bg-void", "--bg-base", "--bg-elevated", "--bg-surface",
            "--bg-surface-hover", "--bg-inset"]
TEXT_PAIRS = [
    (text, surface)
    for text in ("--text-primary", "--text-secondary", "--text-muted")
    for surface in SURFACES
] + [
    # Links, prices and active accents on the surfaces they appear on.
    ("--accent", "--bg-base"),
    ("--accent", "--bg-elevated"),
    ("--accent", "--bg-surface"),
    ("--link", "--bg-base"),
    ("--link-hover", "--bg-base"),
    # Primary button ink across every button state.
    ("--on-accent", "--accent"),
    ("--on-accent", "--accent-hover"),
    ("--on-accent", "--accent-pressed"),
]


@pytest.mark.parametrize("fg,bg", TEXT_PAIRS)
def test_text_token_contrast_meets_aa(fg, bg):
    tokens = _parse_tokens()
    ratio = _contrast_ratio(tokens[fg], tokens[bg])
    assert ratio >= 4.5, f"{fg} on {bg}: {ratio:.2f} < 4.5"


@pytest.mark.parametrize("status", ["undetected", "updating", "detected", "risky", "unknown"])
@pytest.mark.parametrize("surface", ["--bg-base", "--bg-elevated"])
def test_status_label_contrast_on_tint(status, surface):
    """Status pill labels sit on their tint; the tint must flatten over both
    the base page and elevated cards and still carry 4.5:1 text."""
    tokens = _parse_tokens()
    flattened = _composite(tokens[f"--status-{status}-bg"], tokens[surface])
    ratio = _contrast_ratio(tokens[f"--status-{status}"], flattened)
    assert ratio >= 4.5, f"status {status} on tint over {surface}: {ratio:.2f} < 4.5"


@pytest.mark.parametrize("surface", ["--bg-base", "--bg-elevated"])
def test_primary_text_contrast_on_accent_tint(surface):
    """Selected/hover washes use the accent tint; body text on them passes."""
    tokens = _parse_tokens()
    flattened = _composite(tokens["--accent-tint"], tokens[surface])
    ratio = _contrast_ratio(tokens["--text-primary"], flattened)
    assert ratio >= 4.5, f"--text-primary on accent tint over {surface}: {ratio:.2f} < 4.5"


def test_faint_text_is_only_a_decorative_token():
    """--text-faint must never be counted as meaningful text: it exists in the
    palette but is excluded from the AA pairs above by design."""
    tokens = _parse_tokens()
    assert tokens["--text-faint"] == "#5C6470"


def test_old_blue_accent_absent_from_all_css(client):
    for path in ("/static/css/style.css", "/static/css/admin.css"):
        assert "168BFF" not in _css(client, path).upper(), path
    offenders = [p for p in _all_css_files() if "168BFF" in open(p, encoding="utf-8").read().upper()]
    assert offenders == []


def test_old_blue_accent_absent_from_rendered_pages(client, admin_client):
    for path in ("/", "/cheats", "/faq", "/status", "/auth/login"):
        assert "168BFF" not in client.get(path).get_data(as_text=True).upper(), path
    assert "168BFF" not in admin_client.get("/admin/").get_data(as_text=True).upper()


def test_css_tokens_name_accent_and_focus_ring(client):
    css = _css(client, "/static/css/style.css")
    assert re.search(r"--accent:", css)
    assert re.search(r"--on-accent:", css)
    assert "--focus-ring" in css
    assert ":focus-visible{outline:var(--focus-ring-width) solid var(--focus-ring-color)" in css


def test_reduced_motion_block_gates_reveal(client):
    css = _css(client, "/static/css/style.css")
    assert "@media (prefers-reduced-motion:reduce)" in css.replace(": ", ":")
    # The hidden reveal state only applies when motion is allowed.
    gated = re.search(r"@media \(prefers-reduced-motion:no-preference\)\{\.js \.reveal\{opacity:0", css.replace(": ", ":"))
    assert gated, "reveal hidden state must sit inside a no-preference media block"


def test_retired_fonts_removed(client):
    """VAL-DS-006: the display migration replaced Space Grotesk (m1) and Sora
    (pre-mission) with Archivo. Their woff2 files and @font-face rules are
    gone, and only the active font files ship."""
    css = _css(client, "/static/css/style.css")
    assert "Space Grotesk" not in css and "Sora" not in css
    fonts_dir = os.path.join(ROOT, "static", "fonts")
    allowed = {
        "Archivo-var-latin.woff2", "Archivo-var-latin-ext.woff2",
        "Archivo-OFL.txt", "Inter-latin-var.woff2",
        "JetBrainsMono-500-latin.woff2",
    }
    assert set(os.listdir(fonts_dir)) == allowed, sorted(os.listdir(fonts_dir))
    # Every woff2 on disk is declared by the stylesheet (no unused files).
    declared = set(re.findall(r'url\("?(/static/fonts/[^")]+\.woff2)"?\)', css))
    on_disk = {"/static/fonts/" + n for n in allowed if n.endswith(".woff2")}
    assert declared == on_disk, (declared, on_disk)

def test_font_sources_are_self_hosted_only(client, admin_client):
    """VAL-DS-006: every @font-face src points at /static/fonts — no external
    font requests are possible."""
    for path in ("/static/css/style.css", "/static/css/admin.css"):
        for face in re.findall(r"@font-face\{[^}]*\}", _css(client, path)):
            assert "src:" in face and "/static/fonts/" in face, face
            assert "http" not in face, face

def test_css_budgets(client):
    """VAL-DS-002: minified bundle budgets (mission performance target)."""
    style_bytes = os.path.getsize(os.path.join(CSS_DIR, "style.css"))
    admin_bytes = os.path.getsize(os.path.join(CSS_DIR, "admin.css"))
    assert style_bytes <= 80 * 1024, f"style.css {style_bytes}B > 80KB"
    # M4 moved the product_keys.html inline component set (cards, stats,
    # chips, pagination, forms) into admin.css — budget raised 8KB -> 12KB.
    assert admin_bytes <= 12 * 1024, f"admin.css {admin_bytes}B > 12KB"

# Classes from the deleted legacy.css generation (and the dead aliases removed
# with it) that must never reappear in the built bundles or any template.
LEGACY_CLASS_NAMES = (
    "license-card", "skeleton-license", "skeleton-account", "account-panel",
    "account-avatar", "account-username", "account-email", "account-meta",
    "account-actions", "keys-count-badge", "dash-toast", "auth-card",
    "auth-section", "auth-header", "auth-prompt", "auth-title", "auth-benefits",
    "auth-footer", "auth-container", "btn-discord", "review-card-header",
    "review-card-avatar", "review-card-meta", "review-card-rating",
    "review-card-content", "toast-region", "toast-close",
)

def test_legacy_class_names_absent(client, admin_client):
    for path in ("/static/css/style.css", "/static/css/admin.css"):
        body = _css(client, path)
        assert ".toast" not in body, path  # dead .toast-* alias selectors
        for name in LEGACY_CLASS_NAMES:
            assert name not in body, (path, name)
    tpl_dir = os.path.join(ROOT, "templates")
    for dirpath, _dirs, files in os.walk(tpl_dir):
        for name in files:
            if not name.endswith(".html"):
                continue
            src = open(os.path.join(dirpath, name), encoding="utf-8").read()
            for legacy in LEGACY_CLASS_NAMES:
                assert legacy not in src, (os.path.relpath(dirpath, ROOT), name, legacy)

def test_retired_static_assets_removed():
    """Leftover unreferenced assets swept after the cover system landed
    (m1-css-purge / m2-art-direction findings); hero.webp stays as the
    documented OG-fallback candidate (design-direction.md §6)."""
    for rel in (
        "static/loader", "static/images/rust.jpg", "static/images/rust.webp",
        "static/images/header_mockup.svg", "static/icons/rust_placeholder.jpg",
    ):
        assert not os.path.exists(os.path.join(ROOT, rel)), rel
    assert os.path.exists(os.path.join(ROOT, "static", "images", "hero.webp"))

def test_token_mangling_preserves_class_names():
    """The build shortens custom-property names in the bundles. The mangler
    must never touch selector text: every class token in the built bundles
    must exist verbatim in the readable sources."""
    src_classes = set()
    for name in ("tokens.css", "base.css", "components.css", "site.css", "admin.css"):
        src = open(os.path.join(CSS_DIR, "src", name), encoding="utf-8").read()
        src_classes |= set(re.findall(r"\.([a-zA-Z][\w-]*)", src))
    for bundle in ("style.css", "admin.css"):
        built = open(os.path.join(CSS_DIR, bundle), encoding="utf-8").read()
        built_classes = set(re.findall(r"\.([a-zA-Z][\w-]*)", built))
        # "mjs" comes from the generated banner's filename, not a selector.
        built_classes.discard("mjs")
        unexplained = built_classes - src_classes
        assert not unexplained, f"{bundle}: selector corruption {sorted(unexplained)}"

def test_built_css_var_references_resolve():
    """Every var() in the built bundles must resolve to a definition in the
    same bundle pair (style.css + admin.css load together on admin pages)."""
    style = open(os.path.join(CSS_DIR, "style.css"), encoding="utf-8").read()
    admin = open(os.path.join(CSS_DIR, "admin.css"), encoding="utf-8").read()
    defined = set(re.findall(r"[{;](--[\w-]+)(?=:)", style + admin))
    for name, body in (("style.css", style), ("admin.css", admin)):
        refs = set(re.findall(r"var\((--[\w-]+)", body))
        unresolved = refs - defined
        assert not unresolved, f"{name}: unresolved var() {sorted(unresolved)}"


def test_archivo_display_font_self_hosted(client):
    """Archivo variable (wght + wdth axes) is the display face: self-hosted
    woff2 with a width range declared so font-stretch can drive it."""
    css = _css(client, "/static/css/style.css")
    faces = [f for f in re.findall(r"@font-face\{[^}]*\}", css) if "Archivo" in f]
    assert len(faces) == 2  # latin + latin-ext subsets
    for face in faces:
        assert "font-weight:100 900" in face, "variable weight axis missing"
        assert "font-stretch:62% 125%" in face, "width axis range missing"
        assert "font-display:swap" in face
    urls = set(re.findall(r'url\("?(/static/fonts/Archivo-[^")]+\.woff2)"?\)', css))
    assert urls == {"/static/fonts/Archivo-var-latin.woff2",
                    "/static/fonts/Archivo-var-latin-ext.woff2"}
    for url in sorted(urls):
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert resp.data[:4] == b"wOF2", url
    assert '--font-display:"Archivo"' in css.replace(" ", "")


def test_display_font_preloaded_and_ofl_committed(client):
    """base.html preloads the Archivo display font; its OFL licence ships."""
    html = client.get("/").get_data(as_text=True)
    assert 'href="/static/fonts/Archivo-var-latin.woff2" as="font"' in html
    assert "SpaceGrotesk" not in html
    ofl = os.path.join(ROOT, "static", "fonts", "Archivo-OFL.txt")
    assert "SIL OPEN FONT LICENSE" in open(ofl, encoding="utf-8").read().upper()


def test_display_type_drives_width_axis(client):
    """Headings and eyebrows set the Archivo width axis via font-stretch."""
    css = _css(client, "/static/css/style.css")
    assert "--font-stretch-display:115%" in css.replace(" ", "")
    assert "--font-stretch-eyebrow:120%" in css.replace(" ", "")
    assert "--font-weight-display:640" in css.replace(" ", "")
    headings = re.search(r"h1,h2,h3,h4,h5,h6\{[^}]*\}", css)
    assert headings and "font-stretch:var(--font-stretch-display)" in headings.group(0)
    eyebrow = re.search(r"\.micro-label\{[^}]*\}", css)
    assert eyebrow and "font-stretch:var(--font-stretch-eyebrow)" in eyebrow.group(0)


def test_tabular_numerals_convention(client):
    """The mono stack carries tabular-nums by default; .tabular applies it
    anywhere else digits stack or compare (prices, keys, timestamps)."""
    css = _css(client, "/static/css/style.css")
    mono = re.search(r"code,kbd,samp,pre\{[^}]*\}", css)
    assert mono and "font-variant-numeric:tabular-nums" in mono.group(0)
    assert ".tabular{font-variant-numeric:tabular-nums}" in css.replace(" ", "")


def test_review_card_lives_in_components_not_legacy():
    """Review cards are a shared component (m2-homepage migration): the base
    .review-card/.reviews-grid selectors live only in components.css, and the
    legacy.css source that used to shadow them is deleted (VAL-DS-001)."""
    assert not os.path.exists(os.path.join(CSS_DIR, "src", "legacy.css"))
    src = os.path.join(CSS_DIR, "src")
    components = open(os.path.join(src, "components.css"), encoding="utf-8").read()
    assert re.search(r"^\.review-card \{", components, re.M)
    assert re.search(r"^\.reviews-grid \{", components, re.M)
    # Status colors are for STATUS ONLY: the verified-buyer label must not
    # borrow the green status ramp.
    verified = re.search(r"^\.review-card-verified \{[^}]*\}", components, re.M)
    assert verified and "--status-" not in verified.group(0)



def test_no_google_fonts_anywhere(client, admin_client):
    for path in ("/static/css/style.css", "/static/css/admin.css"):
        body = _css(client, path)
        assert "fonts.googleapis" not in body and "fonts.gstatic" not in body
    pages = [client.get(p).get_data(as_text=True) for p in ("/", "/cheats", "/faq")]
    pages.append(admin_client.get("/admin/").get_data(as_text=True))
    for html in pages:
        assert "fonts.googleapis" not in html and "fonts.gstatic" not in html


def test_base_templates_reference_versioned_bundles(client, admin_client):
    html = client.get("/").get_data(as_text=True)
    assert re.search(r'/static/css/style\.css\?v=\d+', html)
    admin_html = admin_client.get("/admin/").get_data(as_text=True)
    assert re.search(r'/static/css/style\.css\?v=\d+', admin_html)
    assert re.search(r'/static/css/admin\.css\?v=\d+', admin_html)


@pytest.mark.parametrize("path", ["/", "/cheats", "/faq", "/status", "/terms-of-service", "/auth/login"])
def test_header_and_footer_on_every_page(client, path):
    html = client.get(path).get_data(as_text=True)
    assert 'class="site-header' in html
    assert 'class="site-footer' in html
    nav = re.search(r'<nav class="site-nav"[^>]*>(.*?)</nav>', html, re.S).group(1)
    pairs = re.findall(
        r'<a href="([^"]+)" class="site-nav__link"[^>]*>\s*([^<]+?)\s*</a>', nav
    )
    assert pairs == [
        ("/cheats", "Cheats"),
        ("/games", "Games"),
        ("/status", "Status"),
        ("/faq", "FAQ"),
        ("/loader", "Setup"),
    ]
    assert "Sign in" in html
    assert 'href="#main-content"' in html and 'id="main-content"' in html


def test_header_shows_account_links_when_signed_in(buyer_client):
    html = buyer_client.get("/").get_data(as_text=True)
    actions = re.search(r'<div class="site-header__actions">(.*?)</div>', html, re.S).group(1)
    assert "My Keys" in actions and "Account" in actions
    assert "Sign in" not in actions


def test_active_nav_item_marked_current(client):
    html = client.get("/faq").get_data(as_text=True)
    assert re.search(r'<a href="/faq" class="site-nav__link" aria-current="page">FAQ</a>', html)


def test_shell_has_no_fake_status_or_badges(client):
    html = client.get("/").get_data(as_text=True)
    shell = html.split('id="main-content"')[0] + html.split("</main>")[-1]
    for phrase in ("Systems Online", "All systems operational", "ambient-canvas", "bg-grid"):
        assert phrase not in shell, phrase


def test_admin_shell_uses_shared_tokens(admin_client):
    html = admin_client.get("/admin/").get_data(as_text=True)
    assert "admin-sidebar" in html and 'aria-current="page"' in html
    assert "Sign out" in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_built_css_is_up_to_date():
    result = subprocess.run(
        ["node", os.path.join(ROOT, "scripts", "build-css.mjs"), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Admin design-system foundation (VAL-ADM-002/003/004): markup hygiene,
# defined-token law, shared partials, confirm dialog instead of bare dialogs.
# ---------------------------------------------------------------------------

ADMIN_DIR = os.path.join(ROOT, "templates", "admin")


def _admin_templates():
    return sorted(
        os.path.join(ADMIN_DIR, name)
        for name in os.listdir(ADMIN_DIR)
        if name.endswith(".html")
    )


def _admin_src(name):
    return open(os.path.join(ADMIN_DIR, name), encoding="utf-8").read()


def test_admin_templates_have_no_inline_styles_or_style_blocks():
    """VAL-ADM-002: no inline style= attributes at all and no page <style>
    blocks — component styles live in admin.css only."""
    offenders = {}
    for path in _admin_templates():
        src = open(path, encoding="utf-8").read()
        problems = []
        for m in re.finditer(r'<[^>]+\bstyle="', src):
            problems.append("style= attribute: " + m.group(0)[:80])
        if "<style" in src:
            problems.append("inline <style> block")
        if problems:
            offenders[os.path.basename(path)] = problems
    assert offenders == {}, offenders


def test_admin_templates_have_no_inline_event_handlers():
    """VAL-ADM-002 companion: no on*= inline handlers (Alpine attributes are
    fine). Bulk select-all and confirms run through script.js delegation."""
    offenders = {}
    for path in _admin_templates():
        src = open(path, encoding="utf-8").read()
        hits = re.findall(r'\bon(click|submit|change|input|load|error)\s*=', src)
        if hits:
            offenders[os.path.basename(path)] = sorted(set(hits))
    assert offenders == {}, offenders


def test_admin_templates_reference_only_defined_css_vars():
    """VAL-ADM-002: every var(--x) in an admin template resolves to a custom
    property defined in the src stylesheets (legacy tokens like --accent-warm
    or --text-mut are gone)."""
    defined = set()
    for name in os.listdir(os.path.join(CSS_DIR, "src")):
        if not name.endswith(".css"):
            continue
        src = open(os.path.join(CSS_DIR, "src", name), encoding="utf-8").read()
        defined |= set(re.findall(r"(?m)(--[\w-]+)\s*:", src))
    unresolved = {}
    for path in _admin_templates():
        src = open(path, encoding="utf-8").read()
        refs = set(re.findall(r"var\((--[\w-]+)", src))
        missing = refs - defined
        if missing:
            unresolved[os.path.basename(path)] = sorted(missing)
    assert unresolved == {}, unresolved


def test_admin_templates_use_no_bare_confirm_or_alert():
    """VAL-ADM-004: destructive actions confirm through the shared dialog
    component (data-confirm + partials/confirm_dialog.html), never bare
    confirm()/alert()."""
    offenders = {}
    for path in _admin_templates():
        src = open(path, encoding="utf-8").read()
        hits = re.findall(r"\b(confirm|alert)\s*\(", src)
        if hits:
            offenders[os.path.basename(path)] = hits
    assert offenders == {}, offenders


def test_admin_base_includes_confirm_dialog_partial():
    """VAL-ADM-004: the shared dialog ships once from the admin shell and is
    wired to script.js's accept hook."""
    src = _admin_src("base.html")
    assert 'include "partials/confirm_dialog.html"' in src
    dialog = open(os.path.join(ROOT, "templates", "partials", "confirm_dialog.html"), encoding="utf-8").read()
    assert 'id="confirm-dialog"' in dialog
    assert 'id="confirm-dialog-accept"' in dialog
    assert "data-modal-static" in dialog  # backdrop click never confirms


def test_admin_shared_partials_used_on_list_pages():
    """VAL-ADM-003: filter chips and windowed pagination come from the shared
    partials with identical markup across the list pages."""
    for name in ("orders.html", "keys.html", "users.html"):
        assert 'include "partials/admin_pagination.html"' in _admin_src(name), name
    for name in ("orders.html", "keys.html"):
        assert 'include "partials/admin_filter_chips.html"' in _admin_src(name), name
    assert 'include "partials/admin_filter_chips.html"' in _admin_src("product_keys.html")
    # product_keys' former inline component set now lives in admin.css src.
    admin_css = open(os.path.join(CSS_DIR, "src", "admin.css"), encoding="utf-8").read()
    for cls in (".admin-card", ".admin-stat-card", ".admin-select", ".admin-grid-4",
                ".chip", ".admin-stat-value"):
        assert cls in admin_css, cls


def test_admin_pagination_partial_is_windowed():
    """VAL-ADM-003: the pagination partial collapses long page runs into an
    ellipsis gap instead of rendering every page number."""
    src = open(os.path.join(ROOT, "templates", "partials", "admin_pagination.html"), encoding="utf-8").read()
    assert "pagination-gap" in src
    assert "p >= pg.page - 2" in src and "p <= pg.page + 2" in src
    assert 'aria-label="Pagination"' in src


def test_script_js_has_confirm_and_bulk_select_setup():
    js = open(os.path.join(ROOT, "static", "js", "script.js"), encoding="utf-8").read()
    assert "function setupConfirmDialogs()" in js
    assert "function setupBulkSelect()" in js
    assert 'getElementById("confirm-dialog")' in js
    # Both init paths (DOMContentLoaded + already-loaded) register them.
    assert js.count("setupConfirmDialogs();") == 2
    assert js.count("setupBulkSelect();") == 2


def test_admin_pages_render_shared_components(admin_client):
    """VAL-ADM-002/003/004 rendered: every admin page ships the confirm
    dialog + form-system classes; list pages render chips/pagination partial
    markup; no page renders a var() reference or inline style on a control."""
    pages = {
        "/admin/": ["admin-stat-card", "id=\"confirm-dialog\""],
        "/admin/products": ["admin-card", "data-require-checked", "admin-hidden-forms"],
        "/admin/orders": ["chip", "id=\"confirm-dialog\""],
        "/admin/keys": ["chip", "empty-state"],
        "/admin/users": ["admin-actions"],
        "/admin/reviews": ["admin-toolbar"],
        "/admin/settings": ["input-reveal", "admin-card"],
        # ChairFBI errors out under synthetic test creds, so only the alert
        # branch renders (stat cards + confirm forms are behind the same call).
        "/admin/chairfbi": ["cf-alert"],
    }
    for path, needles in pages.items():
        html = admin_client.get(path).get_data(as_text=True)
        assert html, path
        for needle in needles:
            assert needle in html, f"{path}: missing {needle}"
        # No undefined-var references survive into any rendered admin page.
        assert not re.search(r"var\(--(accent-warm|accent-2|shadow-soft|display|radius|text-mut|accent-h|accent-primary)\b", html), path
        # No bare style= on any element in any rendered admin page.
        assert not re.search(r'<[a-z][^>]*\bstyle="', html), path


def test_admin_empty_states_use_the_shared_partial():
    """VAL-ADM-001: no admin template renders a bare "No X yet/found." row —
    empty lists come from the shared empty-state partial (icon + title +
    sentence + action)."""
    for path in _admin_templates():
        src = open(path, encoding="utf-8").read()
        # Bare text nodes like <td>No keys found.</td> (the empty-state
        # partial's empty_title assignments are quoted vars, never '>'-led).
        assert not re.search(r">\s*No \w+ (yet|found)", src), os.path.basename(path)


# ---------------------------------------------------------------------------
# m5-a11y-motion: reduced-motion gating, 44px touch targets, lazy live-region
# ---------------------------------------------------------------------------

def test_toast_dismiss_transform_gated_by_reduced_motion():
    """VAL-DS-004 (m1 scrutiny r1): the 8px toast-dismiss slide is decorative
    and must only run when motion is allowed. The base .is-dismissing rule
    fades to opacity 0 only; the transform lives inside the no-preference
    block, so the global reduce override never applies it."""
    css = open(os.path.join(CSS_DIR, "src", "components.css"), encoding="utf-8").read()
    base = re.search(r"\.flash-message\.is-dismissing\s*\{[^}]*\}", css)
    assert base, "toast dismiss rule missing"
    assert "transform" not in base.group(0), \
        "base dismiss rule must not carry the decorative transform"
    blocks = re.findall(
        r"@media \(prefers-reduced-motion: no-preference\)\s*\{(.*?)\n\}", css, re.S)
    assert any(
        ".flash-message.is-dismissing" in block and "transform: translateX(8px)" in block
        for block in blocks), \
        "dismiss slide must sit inside a prefers-reduced-motion: no-preference block"


def test_primary_controls_meet_44px_touch_target():
    """VAL-RSP-004 (m5): the tap-target token is 44px and every control family
    that carries a primary interaction consumes it: keys filter chips,
    header action buttons, hero status link, toast dismiss, and admin filter
    chips. (Nav links, steppers, tabs, plan rows and gateway cards already
    consumed var(--tap-target) before this pass.)"""
    tokens = _parse_tokens()
    assert tokens["--tap-target"] == "44px"
    site = open(os.path.join(CSS_DIR, "src", "site.css"), encoding="utf-8").read()
    comps = open(os.path.join(CSS_DIR, "src", "components.css"), encoding="utf-8").read()
    admin = open(os.path.join(CSS_DIR, "src", "admin.css"), encoding="utf-8").read()
    rules = [
        (site, r"\.keys-toolbar \.chip\s*\{[^}]*min-height:\s*var\(--tap-target\)"),
        (site, r"\.home-hero__panel \.btn-link\s*\{[^}]*min-height:\s*var\(--tap-target\)"),
        (site, r"\.site-header__actions \.btn\s*\{[^}]*min-height:\s*var\(--tap-target\)"),
        (comps, r"\.flash-close\s*\{[^}]*width:\s*var\(--tap-target\)"),
        (admin, r"\.chip\s*\{[^}]*min-height:\s*var\(--tap-target\)"),
    ]
    for css, pattern in rules:
        assert re.search(pattern, css), pattern


def test_js_toasts_render_into_lazy_aria_live_region():
    """m1 scrutiny r1 routing: JS-created toasts on flash-less pages must
    lazily create the .flash-container aria-live=polite region instead of
    depending on a flash-rendered container being present."""
    js = open(os.path.join(ROOT, "static", "js", "script.js"), encoding="utf-8").read()
    assert 'region.setAttribute("aria-live", "polite")' in js
    assert "document.body.appendChild(region)" in js
    assert "toastRegion().appendChild(toast)" in js
