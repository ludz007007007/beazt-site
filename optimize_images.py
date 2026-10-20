"""Optimize BEAZT image assets -> WebP + compressed PNG fallback."""
from pathlib import Path
from PIL import Image

IMG_DIR = Path(__file__).parent / "static" / "images"

# (filename, max_width, keep_alpha)
#
# All original PNG/JPG sources (BeaztLogo.png, Logo.png, header.png, hero.png,
# rust.jpg) were converted to WebP and retired during the redesign's asset
# purge (m1-css-purge, m3-legacy-deletion); only their .webp outputs ship.
# Add a source file here when introducing a new raster asset.
TARGETS: list[tuple[str, int, bool]] = []

def process(name, max_width, keep_alpha):
    src = IMG_DIR / name
    if not src.exists():
        print(f"SKIP (missing): {name}")
        return

    img = Image.open(src)
    # Coerce modes
    if keep_alpha and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
    else:
        if img.mode != "RGB":
            img = img.convert("RGB")

    # Downscale if wider than max
    if img.width > max_width:
        h = round(img.height * max_width / img.width)
        img = img.resize((max_width, h), Image.LANCZOS)

    stem = src.stem
    orig_kb = src.stat().st_size / 1024

    # WebP
    webp = IMG_DIR / f"{stem}.webp"
    img.save(webp, "WEBP", quality=82, method=6)
    webp_kb = webp.stat().st_size / 1024

    # Optimized PNG fallback (only for originals that were PNG)
    png_kb = orig_kb
    if src.suffix.lower() == ".png":
        png_fb = IMG_DIR / f"{stem}.png"  # overwrite with optimized
        img.save(png_fb, "PNG", optimize=True)
        png_kb = png_fb.stat().st_size / 1024

    print(f"{name}: {orig_kb:.0f}KB -> WEBP {webp_kb:.0f}KB / PNG {png_kb:.0f}KB  ({img.size[0]}x{img.size[1]})")

for t in TARGETS:
    process(*t)

print("Done.")
