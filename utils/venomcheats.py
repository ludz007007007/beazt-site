import re
import json
import logging
import os
import time
from pathlib import Path
from datetime import datetime, timezone

import requests
from flask import current_app

logger = logging.getLogger(__name__)

BASE_URL = "https://venomcheats.net"
HOMEPAGE_URL = f"{BASE_URL}/en"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

CAPABILITY_NAMES = {
    "esp": "ESP/Wallhack",
    "aimbot": "Aimbot",
    "rcs": "Recoil Control",
    "trigger": "Trigger Bot",
    "triggerbot": "Trigger Bot",
    "radar": "Radar",
    "stream": "Stream Proof",
    "spoofer": "Bonus HWID Spoofer",
    "controllerSupport": "Controller Support (Native)",
    "memoryAimbot": "Memory Aimbot",
    "worldEsp": "World ESP",
    "noRecoil": "No Recoil",
    "noSpread": "No Spread",
    "noSway": "No Sway",
    "fakeDuck": "Fake Duck",
    "skinChanger": "Skin Changer",
    "autoBhop": "Auto Bhop",
    "rapidFire": "Rapid Fire",
    "chams": "Chams",
    "eletronics": "Electronics",
    "exploits": "Exploits",
    "gadgets": "Gadgets",
    "silent": "Silent Aim",
}

SYSTEM_FEATURES = [
    {
        "title": "Polymorphic Engine v4.1.0 Active",
        "description": "Code mutates on every injection. No traces are left in memory, making detection hard for anticheat providers.",
    },
    {
        "title": "Stream Proof",
        "description": "Completely invisible on OBS, Discord, and all recording software. Stream with confidence.",
    },
    {
        "title": "Zero FPS Loss",
        "description": "Our cheat is built for performance. No impact on your FPS, no stuttering, just smooth gameplay.",
    },
    {
        "title": "Kernel Driver",
        "description": "Operating at Ring-0 (Kernel Level) with 0% Performance Loss. Features Stealth Mode and Zero Traces technology.",
    },
]

CHAIRFBI_TO_VENOM = {
    "apex legends": "apex-legends",
    "apex": "apex-legends",
    "arc raiders": "arc-raiders",
    "arc": "arc-raiders",
    "call of duty": "cod",
    "call of duty series": "cod",
    "cod": "cod",
    "fortnite": "fortnite",
    "rainbow six": "rainbowsix",
    "rainbowsix": "rainbowsix",
    "r6": "rainbowsix",
    "rust": "rust",
    "rust external": "rust",
    "pubg": "pubg",
    "pubg: battlegrounds": "pubg",
    "marvel rivals": "marvel",
    "marvel": "marvel",
}

STATUS_MAP = {
    "UNDETECTED": "online",
    "UPDATE": "maintenance",
    "UPDATING": "maintenance",
    "DETECTED": "offline",
    "UNKNOWN": "offline",
}


def _extract_products_from_html(html):
    """Extract the allCheatsForStatus array directly from raw HTML."""
    marker = 'allCheatsForStatus'
    idx = html.find(marker)
    if idx == -1:
        logger.warning("allCheatsForStatus marker not found in HTML")
        return []

    bracket_start = html.find(':[', idx)
    if bracket_start == -1:
        logger.warning("allCheatsForStatus array bracket not found")
        return []
    bracket_start += 1

    depth = 0
    i = bracket_start
    while i < len(html):
        c = html[i]
        if c == '\\':
            i += 2
            continue
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                raw = html[bracket_start:i + 1]
                try:
                    data = json.loads(raw.encode().decode('unicode_escape'))
                except (UnicodeDecodeError, UnicodeEncodeError, json.JSONDecodeError):
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("Failed to parse allCheatsForStatus JSON")
                        return []
                if isinstance(data, list) and len(data) > 0:
                    logger.info("Extracted %d products from allCheatsForStatus", len(data))
                    return data
                return []
        i += 1

    logger.warning("Failed to close allCheatsForStatus bracket")
    return []


def _fetch_homepage():
    """Fetch and parse the VenomCheats homepage for product data."""
    logger.info("Fetching VenomCheats homepage: %s", HOMEPAGE_URL)
    resp = requests.get(HOMEPAGE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text

    all_products = _extract_products_from_html(html)

    if all_products:
        products = []
        seen_slugs = set()
        for p in all_products:
            slug = p.get("slug", "")
            name = p.get("name", p.get("game", ""))
            key = (slug, name)
            if key not in seen_slugs:
                seen_slugs.add(key)
                products.append(p)
        logger.info("Found %d products from VenomCheats", len(products))
        return products

    logger.warning("No products found from VenomCheats — HTML may have changed")
    return []


def get_all_products():
    """Fetch all VenomCheats products with full metadata."""
    return _fetch_homepage()


def match_chairfbi_to_venom(chairfbi_name):
    """Match a ChairFBI cheat name to a VenomCheats slug."""
    if not chairfbi_name:
        return None

    name_lower = chairfbi_name.strip().lower()

    if name_lower in CHAIRFBI_TO_VENOM:
        return CHAIRFBI_TO_VENOM[name_lower]

    for key, slug in CHAIRFBI_TO_VENOM.items():
        if key in name_lower or name_lower in key:
            return slug

    return None


def find_product_by_slug(products, slug):
    """Find the primary product entry for a given slug."""
    matches = [p for p in products if p.get("slug") == slug]
    if not matches:
        return None
    matches.sort(key=lambda p: (p.get("status") != "UNDETECTED", int(p.get("id", 99))))
    return matches[0]


def get_capability_names(capability_keys):
    """Convert capability key list to display names."""
    return [CAPABILITY_NAMES.get(k, k.replace("_", " ").title()) for k in capability_keys]


def get_system_features():
    """Return shared system architecture features."""
    return SYSTEM_FEATURES


def build_features_text(product):
    """Build a multiline features text from product capabilities."""
    caps = product.get("capabilities", [])
    names = get_capability_names(caps)
    return "\n".join(f"- {n}" for n in names)


def build_description(product):
    """Build a rich description from product data."""
    caps = product.get("capabilities", [])
    cap_names = get_capability_names(caps)
    cap_text = ", ".join(cap_names)

    return (
        f"{product.get('name', '')} - Undetected cheat with {len(caps)} features.\n\n"
        f"Features: {cap_text}\n\n"
        f"OS: {product.get('operatingSystem', 'Windows 10-11')}\n"
        f"CPU: {product.get('processor', 'Intel & AMD')}\n"
        f"Anti-Cheat: {product.get('antiCheat', 'N/A')}\n\n"
        f"Status: {product.get('status', 'UNKNOWN')}"
    )


def get_media_urls(product):
    """Extract all media URLs (images and videos) from a product."""
    images = []
    videos = []
    media_list = product.get("media", [])
    for m in media_list:
        mtype = m.get("type", "image")
        url = m.get("url", "")
        if not url:
            continue
        if mtype == "video":
            videos.append(url)
        else:
            if url.startswith("/"):
                url = f"{BASE_URL}{url}"
            images.append(url)
    return images, videos


def get_logo_url(product):
    """Get the full product logo URL."""
    logo = product.get("image", "")
    if not logo:
        return None
    if logo.startswith("/"):
        return f"{BASE_URL}{logo}"
    return logo


def download_image(url, save_path):
    """Download a single image to a local path."""
    try:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        if os.path.exists(save_path):
            return True
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(resp.content)
        logger.debug("Downloaded: %s -> %s", url, save_path)
        return True
    except Exception as e:
        logger.warning("Failed to download %s: %s", url, e)
        return False


def download_product_media(product, static_dir):
    """Download all product images and logo to static directory.

    On read-only filesystems (Vercel), returns remote VenomCheats CDN URLs.
    """
    slug = product.get("slug", "unknown")
    images, _videos = get_media_urls(product)

    try:
        base_dir = Path(static_dir) / "images" / "venomcheats" / slug
        base_dir.mkdir(parents=True, exist_ok=True)

        downloaded = []
        for i, img_url in enumerate(images):
            ext = os.path.splitext(img_url.split("?")[0])[1] or ".webp"
            fname = f"{i + 1}{ext}"
            save_path = base_dir / fname
            if download_image(img_url, str(save_path)):
                downloaded.append(f"/static/images/venomcheats/{slug}/{fname}")

        logo_url = get_logo_url(product)
        if logo_url:
            ext = os.path.splitext(logo_url.split("?")[0])[1] or ".webp"
            logo_path = base_dir / f"logo{ext}"
            download_image(logo_url, str(logo_path))

        return downloaded
    except OSError:
        return images


def get_primary_image_url(product):
    """Get the best primary image URL for a product."""
    images, _videos = get_media_urls(product)
    if images:
        return images[0]
    logo = get_logo_url(product)
    if logo:
        return logo
    return None


def extract_rating(html):
    """Extract Trustpilot rating from HTML."""
    ld_json = re.search(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if ld_json:
        try:
            data = json.loads(ld_json.group(1))
            if isinstance(data, dict):
                rating = data.get("aggregateRating", {})
                if isinstance(rating, dict):
                    return {
                        "value": rating.get("ratingValue"),
                        "count": rating.get("reviewCount"),
                        "best": rating.get("bestRating"),
                        "url": "https://www.trustpilot.com/review/venomcheats.net",
                    }
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        rating = item.get("aggregateRating", {})
                        if rating:
                            return {
                                "value": rating.get("ratingValue"),
                                "count": rating.get("reviewCount"),
                                "best": rating.get("bestRating"),
                                "url": "https://www.trustpilot.com/review/venomcheats.net",
                            }
        except json.JSONDecodeError:
            pass
    return None


def get_rating():
    """Fetch current Trustpilot rating from VenomCheats."""
    try:
        resp = requests.get(HOMEPAGE_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return extract_rating(resp.text)
    except Exception as e:
        logger.warning("Failed to fetch rating: %s", e)
        return None


def sync_all(static_dir=None):
    """Full sync: fetch all products, return enriched data.

    Returns a dict mapping venom_slug -> product_data.
    """
    products = get_all_products()
    if not products:
        logger.error("No products found from VenomCheats")
        return {}

    result = {}
    for p in products:
        slug = p.get("slug", "")
        if slug not in result:
            result[slug] = p

    if static_dir:
        for p in result.values():
            download_product_media(p, static_dir)

    logger.info("Synced %d VenomCheats products", len(result))
    return result


def fetch_product_pricing(slug, timeout=15):
    """Fetch pricing tiers from an individual VenomCheats product page.

    Returns list of (label, duration_days, price_usd) tuples, or None on failure.
    """
    url = f"{BASE_URL}/en/cheats/{slug}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Failed to fetch pricing for %s: %s", slug, e)
        return None

    tiers = re.findall(
        r'(\d+)\s+(Day|Days).*?\$(\d+\.\d{2})',
        resp.text, re.DOTALL,
    )

    if not tiers:
        logger.warning("No pricing tiers found for %s", slug)
        return None

    result = []
    seen = set()
    for days_str, _, price_str in tiers:
        days = int(days_str)
        if days not in seen:
            seen.add(days)
            label = f"{days} Day{'s' if days > 1 else ''}"
            result.append((label, days, float(price_str)))

    if result:
        result.sort(key=lambda x: x[1])
        logger.info("Extracted %d pricing tiers for %s", len(result), slug)
        return result
    return None
