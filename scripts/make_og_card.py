"""Regenerate static/images/og-default.png — the default OG brand card.

Run from the repo root after changing utils/covers.py brand_card_png():
    .venv\\Scripts\\python.exe scripts\\make_og_card.py

The committed PNG is the artifact referenced by templates/base.html
(og:image default for every non-product page), so it only changes when this
script is re-run.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.covers import brand_card_png  # noqa: E402


def main():
    out = os.path.join(ROOT, "static", "images", "og-default.png")
    with open(out, "wb") as fh:
        fh.write(brand_card_png())
    print(f"wrote {out} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
