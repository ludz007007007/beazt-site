"""Sitewide copy canon enforcement (m3-copy-canon, VAL-CON-005).

Every template is scanned for retired jargon and contradictory claims:

- "Operator" title jargon ("Operator Login", "Create Operator", and the whole
  word in visitor-visible text) is retired — titles and nav use plain words.
- The "Ref" key-meta label is retired ("License ID" or dropped).
- The contradictory delivery claims are banned sitewide; the ONE canonical
  promise lives in partials/copy.html (guards imported from test_content_pages).

Nav labels must match their destinations (Cheats · Games · Status · FAQ ·
Setup), the desktop nav and the mobile panel agree, and the support paths
(FAQ, loader guide, Discord) are reachable from the footer help strip.
"""

import os
import re

from test_content_pages import CANONICAL_PROMISE, RETIRED_CLAIMS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL_DIR = os.path.join(ROOT, "templates")

# Banned verbatim — may appear anywhere in template source (titles,
# aria-labels, placeholders, meta), not just in visible text.
BANNED_STRINGS = (
    "Operator Login",
    "Create Operator",
    "operator desk",
)

# Retired vocabulary words: banned as whole words in visitor-visible text.
RETIRED_WORDS = ("operator", "ref")

# Header furniture (architecture §4): label -> destination.
NAV_PAIRS = [
    ("Cheats", "/cheats"),
    ("NFA Accounts", "/nfa"),
    ("Games", "/games"),
    ("Status", "/status"),
    ("FAQ", "/faq"),
    ("Setup", "/loader"),
]


def _all_templates():
    """(relative path, source) for every template in the tree."""
    for dirpath, _dirs, files in os.walk(TPL_DIR):
        for name in files:
            if name.endswith(".html"):
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, TPL_DIR).replace("\\", "/")
                yield rel, open(path, encoding="utf-8").read()


def _visible_text(src):
    """Template source stripped of Jinja blocks, tags and comments: the text a
    visitor can actually read (script bodies included — they must be jargon
    free too, since they surface in toasts and injected markup)."""
    src = re.sub(r"\{#.*?#\}", " ", src, flags=re.S)
    src = re.sub(r"\{\{.*?\}\}", " ", src, flags=re.S)
    src = re.sub(r"\{%.*?%\}", " ", src, flags=re.S)
    return re.sub(r"<[^>]+>", " ", src)


# ---- VAL-CON-005: retired jargon and claims --------------------------------

def test_banned_jargon_strings_absent_from_all_templates():
    for rel, src in _all_templates():
        for banned in BANNED_STRINGS:
            assert banned not in src, f"{rel}: {banned!r}"


def test_retired_jargon_words_absent_from_visible_text():
    for rel, src in _all_templates():
        text = _visible_text(src)
        for word in RETIRED_WORDS:
            hits = re.findall(rf"\b{word}\b", text, re.I)
            assert not hits, f"{rel}: retired jargon word {word!r} in visible text"


def test_retired_delivery_claims_absent_from_all_templates():
    for rel, src in _all_templates():
        for banned in RETIRED_CLAIMS:
            assert banned not in src, f"{rel}: {banned!r}"


def test_canonical_promise_defined_exactly_once():
    """Single source of truth for the delivery promise (partials/copy.html)."""
    hits = [rel for rel, src in _all_templates() if CANONICAL_PROMISE in src]
    assert hits == ["partials/copy.html"], hits


# ---- VAL-CON-005: nav labels match destinations ----------------------------

def _parse_nav(html, cls):
    nav = re.search(rf'<nav class="{cls}"[^>]*>(.*?)</nav>', html, re.S)
    assert nav, f"nav {cls} not found"
    hrefs_labels = re.findall(
        rf'<a href="([^"]+)" class="{cls}__link"[^>]*>\s*([^<]+?)\s*</a>',
        nav.group(1),
    )
    return [(label.strip(), href) for href, label in hrefs_labels]


def test_desktop_nav_labels_match_destinations(client):
    html = client.get("/").get_data(as_text=True)
    assert _parse_nav(html, "site-nav") == NAV_PAIRS


def test_mobile_panel_shows_the_same_nav(client):
    html = client.get("/").get_data(as_text=True)
    panel = _parse_nav(html, "mobile-menu")
    assert panel[: len(NAV_PAIRS)] == NAV_PAIRS


def test_support_paths_reachable_from_footer_help_strip(client):
    html = client.get("/").get_data(as_text=True)
    footer = re.search(r'<footer class="site-footer".*?</footer>', html, re.S).group(0)
    help_strip = re.search(
        r'<h2 class="site-footer__heading" id="footer-help">.*?</nav>', footer, re.S
    ).group(0)
    assert 'href="/faq"' in help_strip
    assert 'href="/loader"' in help_strip
    assert re.search(r'href="https://discord\.gg/[^"]+"', help_strip)
    # The renamed destinations themselves are live.
    assert client.get("/loader").status_code == 200
    assert client.get("/games").status_code == 200
