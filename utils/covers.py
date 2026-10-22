"""Typographic cover generator (SIGNAL art direction, design-direction.md §6).

Every product and game renders a deterministic 16:9 cover: graphite field,
game wordmark set in Archivo expanded caps, a status-color accent bar on the
left edge, and a subtle geometric motif derived from a hash of the game slug.
No stock imagery is involved, so covers are always crisp and never shared
between games. A small variant index shifts the motif framing so a product
gallery can show several distinct typographic shots of the same product.

Colors mirror static/css/src/tokens.css (primitives layer). If tokens change,
re-align the RGB tuples here — tests/test_covers.py pins the taxonomy keys.
"""

import io
import zlib
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from utils.catalogue import STATUS_LABELS

# 16:9 master size. Markup references these intrinsic dimensions
# (width="1200" height="675"); anything displayed smaller is downscaled.
COVER_W, COVER_H = 1200, 675

_FONT_PATH = "assets/fonts/Archivo-VariableFont.ttf"

# tokens.css primitives (RGB) — keep in sync with the CSS ramp.
GRAPHITE_BASE = (16, 19, 24)      # --graphite-900 field
BONE_50 = (242, 240, 234)         # --bone-50 wordmark
BONE_300 = (184, 186, 196)        # --bone-300 secondary text
BONE_500 = (142, 150, 163)        # --bone-500 muted text
AMBER = (232, 163, 61)            # --amber-500 (brand card tick only)

# Status family — same taxonomy keys as utils/catalogue.py STATUS_LABELS.
# "down" carries no dedicated token; it renders in the neutral grey like the
# pill component does.
STATUS_COLORS = {
    "undetected": (70, 208, 140),
    "updating": (95, 168, 232),
    "risky": (245, 154, 74),
    "detected": (240, 87, 95),
    "down": (152, 160, 172),
    "unknown": (152, 160, 172),
    # Neutral violet for NFA/account products (no detection lifecycle).
    "account": (167, 139, 250),
}

_FONT_CACHE = {}


def _font(size, weight=660, width=125):
    """Archivo instance with the variable axes pinned (Weight first in this
    build's fvar order — verified against get_variation_axes())."""
    key = (size, weight, width)
    font = _FONT_CACHE.get(key)
    if font is None:
        font = ImageFont.truetype(_FONT_PATH, size)
        try:
            font.set_variation_by_axes([float(weight), float(width)])
        except Exception:
            pass  # non-variable fallback: plain Archivo is still on-brand
        _FONT_CACHE[key] = font
    return font


def _tracked_text(draw, xy, text, font, fill, tracking=0):
    """Draw text with per-character tracking (Pillow has no letter-spacing)."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


def _tracked_width(draw, text, font, tracking=0):
    if not text:
        return 0
    return sum(draw.textlength(ch, font=font) for ch in text) + tracking * (len(text) - 1)


def _fit_size(draw, text, max_width, lo=64, hi=220, weight=660, width=125):
    """Largest size whose single-line rendering fits max_width."""
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        if draw.textlength(text, font=_font(mid, weight, width)) <= max_width:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return best


def _wordmark_lines(draw, game, max_width):
    """Game wordmark as (lines, size): one line when it fits large enough,
    otherwise a balanced two-line split at a space."""
    game = game.upper()
    size = _fit_size(draw, game, max_width)
    if size >= 130 or " " not in game:
        return [game], size
    words = game.split(" ")
    # Split at the space that leaves the most balanced pair of lines.
    best_pair, best_spread = None, None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        wa = draw.textlength(a, font=_font(100))
        wb = draw.textlength(b, font=_font(100))
        spread = abs(wa - wb)
        if best_spread is None or spread < best_spread:
            best_spread, best_pair = spread, (a, b)
    a, b = best_pair
    size = min(_fit_size(draw, a, max_width, hi=190), _fit_size(draw, b, max_width, hi=190))
    return [a, b], size


def _motif(draw, seed, variant, w, h):
    """Deterministic per-game geometry, <8% visual weight (bone at ~9% alpha).

    Four families rotated by the variant index so a gallery can show several
    distinct framings of the same product. Always anchored right — the
    wordmark owns the left two-thirds.
    """
    fam = (seed + variant) % 4
    corner = "tr" if (seed >> 3) % 2 == 0 or variant % 2 == 0 else "br"
    stroke = (*BONE_50, 22)
    faint = (*BONE_50, 13)
    m = 40  # margin
    if fam == 0:  # corner ticks
        for length in (110, 60):
            if corner == "tr":
                y = m + (length - 60)
                draw.line([(w - m - length, y), (w - m, y)], fill=stroke, width=4)
                draw.line([(w - m, y), (w - m, y + length)], fill=stroke, width=4)
            else:
                y = h - m - (length - 60)
                draw.line([(w - m - length, y), (w - m, y)], fill=stroke, width=4)
                draw.line([(w - m, y), (w - m, y - length)], fill=stroke, width=4)
        # second, fainter tick echoing the first
        off = 34
        if corner == "tr":
            draw.line([(w - m - 46, m + off + 70), (w - m - off, m + off + 70)], fill=faint, width=3)
        else:
            draw.line([(w - m - 46, h - m - off - 70), (w - m - off, h - m - off - 70)], fill=faint, width=3)
    elif fam == 1:  # scan lines
        box_w, box_h = 330, 210
        x0 = w - m - box_w
        y0 = m if corner == "tr" else h - m - box_h
        for i in range(0, box_h, 18):
            draw.line([(x0, y0 + i), (x0 + box_w, y0 + i)], fill=(*BONE_50, 12), width=2)
        draw.line([(x0, y0), (x0, y0 + box_h)], fill=stroke, width=3)
    elif fam == 2:  # concentric arcs
        cx = w - m
        cy = m if corner == "tr" else h - m
        for r in range(70, 360, 58):
            box = [cx - r, cy - r, cx + r, cy + r]
            draw.arc(box, 90, 180 if corner == "tr" else 270, fill=(*BONE_50, 16), width=3)
    else:  # diagonal hatch
        box = 240
        x0 = w - m - box
        y0 = m if corner == "tr" else h - m - box
        for i in range(-box, box, 26):
            draw.line([(x0 + i, y0 + box), (x0 + i + box, y0)], fill=(*BONE_50, 12), width=2)


@lru_cache(maxsize=256)
def _cover_png_cached(game, product_name, status, variant):
    return _render_cover(game, product_name, status, variant)


def cover_png(game, product_name=None, status="undetected", variant=0):
    """Render a product/game cover and return PNG bytes (deterministic).

    Results are memoized on the full argument tuple: covers are pure
    functions of their inputs, so re-renders are free. The status key is
    part of the cache key, so a status change re-renders immediately.
    """
    variant = max(0, min(int(variant), 3))
    return _cover_png_cached(game, product_name, status, variant)


def _render_cover(game, product_name=None, status="undetected", variant=0):
    """Render a product/game cover and return PNG bytes (deterministic)."""
    variant = max(0, min(int(variant), 3))
    status_rgb = STATUS_COLORS.get(status, STATUS_COLORS["unknown"])
    game_slug = "".join(ch for ch in game.lower() if ch.isalnum())
    seed = zlib.crc32(game_slug.encode("utf-8"))

    img = Image.new("RGB", (COVER_W, COVER_H), GRAPHITE_BASE)
    draw = ImageDraw.Draw(img, "RGBA")

    # Hairline inner frame (the card border equivalent at bitmap scale).
    draw.rectangle([2, 2, COVER_W - 3, COVER_H - 3], outline=(255, 255, 255, 18), width=2)

    # Status accent bar on the left edge — the one saturated element.
    draw.rectangle([0, 0, 12, COVER_H], fill=(*status_rgb, 255))
    draw.rectangle([12, 0, 15, COVER_H], fill=(*status_rgb, 70))

    _motif(draw, seed, variant, COVER_W, COVER_H)

    left = 88
    # Eyebrow: tracked expanded caps.
    eyebrow_font = _font(26, weight=600, width=120)
    _tracked_text(draw, (left, 96), "BEAZT", eyebrow_font, (*BONE_300, 255), tracking=10)

    # Wordmark: game name, Archivo expanded caps, fitted. The block must end
    # above the status line (pinned at COVER_H-92), so shrink until it does.
    lines, size = _wordmark_lines(draw, game, max_width=1000)
    status_y = COVER_H - 92
    while True:
        line_h = int(size * 1.04)
        block_bottom = 210 + line_h * len(lines) + (58 if product_name else 0)
        if block_bottom <= status_y - 24 or size <= 64:
            break
        size -= 6
    word_font = _font(size, weight=660, width=125)
    y = 210
    for line in lines:
        draw.text((left, y), line, font=word_font, fill=(*BONE_50, 255))
        y += int(size * 1.04)

    # Product sub-line (product covers only; game covers stay pure).
    if product_name:
        sub_font = _font(40, weight=500, width=110)
        draw.text((left + 2, y + 18), product_name, font=sub_font, fill=(*BONE_300, 255))

    # Status line: taxonomy word in the product's status color + dot, pinned
    # bottom-left. Mirrors the status pill taxonomy (utils/catalogue.py).
    label = STATUS_LABELS.get(status, "Status").upper()
    label_font = _font(22, weight=600, width=120)
    dot_y = status_y
    draw.ellipse([left, dot_y + 5, left + 14, dot_y + 19], fill=(*status_rgb, 255))
    _tracked_text(draw, (left + 30, dot_y), label, label_font, (*status_rgb, 235), tracking=8)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def brand_card_png():
    """Default OG card for non-product pages: wordmark, tagline, amber tick."""
    img = Image.new("RGB", (COVER_W, COVER_H), GRAPHITE_BASE)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([2, 2, COVER_W - 3, COVER_H - 3], outline=(255, 255, 255, 18), width=2)

    left = 88
    eyebrow_font = _font(26, weight=600, width=120)
    _tracked_text(draw, (left, 150), "GAME CHEATS · HONEST STATUS", eyebrow_font, (*BONE_300, 255), tracking=10)

    size = _fit_size(draw, "BEAZT", 1000, hi=260)
    word_font = _font(size, weight=680, width=125)
    draw.text((left, 220), "BEAZT", font=word_font, fill=(*BONE_50, 255))

    # The amber tick — the one accent on the brand card.
    draw.rectangle([left + 4, 470, left + 4 + 180, 470 + 10], fill=(*AMBER, 255))

    tag_font = _font(34, weight=500, width=110)
    draw.text((left + 2, 508), "Access keys with a live, public status page.", font=tag_font, fill=(*BONE_300, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
