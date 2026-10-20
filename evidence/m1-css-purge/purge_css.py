"""m1-css-purge: remove verified-dead rule families from static/css/src/legacy.css.

Dead families were verified by scanning templates/**/*.html, static/js/*.js and
routes for class references (only comment/substring false-positives remained).
A selector is dropped when ANY of its class tokens belongs to a dead family:
a compound/descendant selector can never match if one referenced class never
appears in markup. Media queries are pruned rule-by-rule and dropped when
empty. Stale @keyframes (no animation reference anywhere) are dropped.
"""

import re
import sys

PATH = "static/css/src/legacy.css"

# Class tokens that are dead only as an exact name (a prefix match would catch
# live classes, e.g. .loader-step-body / .loader-step-actions stay).
DEAD_EXACT = {
    "loader-step",
    "products-grid",
    "store-preview--private",
    "dashboard-header",
    "status-active",
    "status-expired",
}

# Dead families: token == prefix or token.startswith(prefix + "-").
DEAD_PREFIX = {
    # skeleton families (dead copies; -license/-account are LIVE in keys.html)
    "skeleton-card",
    "skeleton-key",
    "btn-discord",
    "stat-bar",
    "feature-card",
    # testimonial v1 + v2 incl. section header (rating-*) and verified-badge
    "testimonial",
    "testimonials",
    "rating-summary",
    "rating-score",
    "rating-stars",
    "rating-count",
    "verified-badge",
    "bento",
    "how-track",
    "how-node",
    # key-card family (superseded by license-card-* in keys.html)
    "key-card",
    "key-header",
    "key-icon",
    "key-info",
    "key-product",
    "key-badges",
    "key-value",
    "key-label",
    "key-copy-btn",
    "key-actions",
    "key-meta",
    "key-status",
    "key-tier-badge",
    "discord-section",
    "discord-content",
    "discord-title",
    "discord-text",
    "discord-meta",
    # loader-steps family (loader.html uses loader-guide-step / loader-step-body)
    "loader-steps",
    "loader-step-number",
    "loader-step-content",
}

# @keyframes with no animation reference in any css/js/html source.
DEAD_KEYFRAMES = {
    "error-appear",
    "status-pulse",
    "status-pulse-warning",
    "status-pulse-error",
    "status-strip-pulse",
    "tab-fade-in",
}

dropped = []


def is_dead_token(tok: str) -> bool:
    if tok in DEAD_EXACT:
        return True
    return any(tok == p or tok.startswith(p + "-") for p in DEAD_PREFIX)


def selector_is_dead(sel: str) -> bool:
    tokens = re.findall(r"\.([A-Za-z0-9_-]+)", sel)
    return any(is_dead_token(t) for t in tokens)


def find_block_end(text: str, open_idx: int) -> int:
    """open_idx points at '{'; return index just past its matching '}'."""
    depth = 0
    i = open_idx
    in_str = None
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "\"'":
            in_str = c
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = (j + 2) if j != -1 else len(text)
            continue
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def skip_noise(text: str, i: int) -> int:
    """Index of next non-whitespace, non-comment char at or after i."""
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = (j + 2) if j != -1 else len(text)
        else:
            break
    return i


def next_brace(text: str, i: int):
    """Find the next top-of-rule '{' starting at i, skipping comments/strings.

    Returns (brace_idx, had_noise) or (None, _) when no rule follows.
    """
    j = i
    while j < len(text):
        c = text[j]
        if text.startswith("/*", j):
            k = text.find("*/", j + 2)
            j = (k + 2) if k != -1 else len(text)
            continue
        if c in "\"'":
            q = c
            j += 1
            while j < len(text):
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == q:
                    break
                j += 1
            j += 1
            continue
        if c == "{":
            return j
        if c == "}":  # stray close brace; treat as noise boundary
            j += 1
            continue
        j += 1
    return None


def filter_css(text: str) -> str:
    out = []
    i = skip_noise(text, 0)
    out.append(text[:i])  # header comments/whitespace
    while i < len(text):
        brace = next_brace(text, i)
        if brace is None:
            out.append(text[i:])
            break
        prelude = text[i:brace]
        end = find_block_end(text, brace)
        body = text[brace + 1 : end - 1]
        stripped = prelude.strip()

        keep = True
        rebuilt = None
        if stripped.startswith("@keyframes"):
            m = re.match(r"@keyframes\s+([\w-]+)", stripped)
            if m and m.group(1) in DEAD_KEYFRAMES:
                keep = False
                dropped.append(stripped)
        elif stripped.startswith("@media"):
            inner = filter_css(body)
            if not inner.strip():
                keep = False
                dropped.append(stripped + "  -> emptied")
            else:
                rebuilt = prelude + "{" + inner + "}"
        else:
            alive = [p for p in prelude.split(",") if not selector_is_dead(p)]
            if not alive:
                keep = False
                dropped.append(stripped)

        if keep:
            out.append(rebuilt if rebuilt is not None else text[i:end])
        nxt = skip_noise(text, end)
        out.append(text[end:nxt])  # inter-rule whitespace/comments
        i = nxt

    result = re.sub(r"\n{3,}", "\n\n", "".join(out))
    if not result.endswith("\n"):
        result += "\n"
    return result


def main() -> None:
    src = open(PATH, encoding="utf-8").read()
    filtered = filter_css(src)
    # safety: no dead token may remain as a selector
    leftovers = {m.group(1) for m in re.finditer(r"\.([A-Za-z0-9_-]+)", filtered)
                 if is_dead_token(m.group(1))}
    if leftovers:
        print("LEFTOVER DEAD TOKENS:", sorted(leftovers))
        sys.exit(1)
    kf = set(re.findall(r"@keyframes\s+([\w-]+)", filtered))
    if kf & DEAD_KEYFRAMES:
        print("LEFTOVER DEAD KEYFRAMES:", sorted(kf & DEAD_KEYFRAMES))
        sys.exit(1)
    # safety: live families must survive
    for live in ["skeleton-license-card", "skeleton-account-panel", "loader-step-body",
                 "loader-guide-step", "license-card", "status-board", "faq-item",
                 "legal-toc", "account-panel", "mobile-buy-bar", "review-card",
                 "status-row-uptime-dot", "status-pulse-online", "dash-toast",
                 "keys-grid", "license-card-key-header"]:
        if live not in filtered:
            print("MISSING LIVE CLASS:", live)
            sys.exit(1)
    open(PATH, "w", encoding="utf-8", newline="\n").write(filtered)
    print(f"before: {len(src)} bytes, after: {len(filtered)} bytes "
          f"({len(src) - len(filtered)} removed, "
          f"{100 * (len(src) - len(filtered)) / len(src):.1f}%)")
    print(f"dropped {len(dropped)} rules/keyframes/media blocks")
    print("all safety checks passed")


if __name__ == "__main__":
    main()
