"""Seed the Rust product line: full external build + BEAZT Legit.

Idempotent: safe to run repeatedly (local and server). Updates the existing
full product (rust-external-private) with the complete feature list from the
r9 menu, and creates the restricted Legit build (rust-beazt-legit) with
ESP/radar-only features and its own pricing tiers.

Run inside the app environment:
    python scripts/set_rust_products.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db, Product, PricingTier  # noqa: E402

FULL_FEATURES = """Memory Aimbot — bone-targeted, silent on your inputs
Adjustable Smoothing + FOV size
Keep Target (sticks to one victim, no flicker)
Humanized Aim — Smooth Variance + First Shot Miss
Fire Gated / Input Correlated write gating
Bone selection, target filters, teammate ignore
Max distance + visibility rules
Aim line, target info, hit feedback
Recoil Mod — written into weapon recoil properties
Recoil Variance + Recoil Floor (looks human, never robotic)
Box (corner/normal/filled) + Box Outline & Glow
Skeleton with outline, glow, joints, thickness control
Head Circle + Player Circle (glow options)
Health, names, weapons, distance, team detection
VisCheck — visibility-aware colors
Ammo Bar, Movement Trails, Advanced Distances
Adjustable ESP font size + distance style
Sleepers, filters
NPC ESP — scientists, tunneled NPCs, full styling
Animal ESP — bears, wolves, boars, horses, chickens
Resources: Stone / Metal / Sulfur / HQM Ore, Hemp
Traps: Auto Turret, Shotgun Trap, SAM Site, Bear Trap, Landmine, Flame Turret
Pickups & Loot: stashes, corpses, body bags, dropped items
Raid ESP + Raid Distance, Crate Timer
On-screen radar — players, NPCs, animals
Grid + rotate-with-you, background opacity, dot glow, custom colors
Hide sleepers, remove team marks
Bright Night — full-brightness nights
Time Changer
FOV Changer + Zoom (ADS-aware)
Admin Flags
Debug Camera (scout mode — fly the map, bounded & safe)
Battle Mode + per-category filters
Combat Mode, Human Safe Mode
Mark Team / Clear Team Marks
Double Jump, No Fall Damage
Unlimited named configs — create / save / load / delete
Auto Save
Full Keybind Manager (search, conflict detection, per-feature mode)
Quick Presets: Legit / Aggressive / Farmer / ESP Only / Server-Safe
Language selection (English / Russian)"""

FULL_DESCRIPTION = (
    "The clean external. Memory-based, overlay-driven, built around a full "
    "config system. Humanized aim and recoil, full player/NPC/animal/world "
    "ESP with VisCheck, on-screen radar, Bright Night, admin flags, debug "
    "camera, battle mode and unlimited configs with one-click presets."
)

LEGIT_FEATURES = """Full Player ESP — box, skeleton, head circle, VisCheck
Health, names, weapons, distances
NPC ESP and Animal ESP
World ESP — resources, traps, loot, raid ESP
Radar — players / NPCs / animals, sleepers, team colors
Bright Night
Admin Flags
Debug Camera (scout mode)
Battle Mode — instant toggle to your saved ESP/radar setup
Own config file + presets — never inherits combat settings
No combat features — cannot aim for you"""

LEGIT_DESCRIPTION = (
    "The restricted build. No combat features, period — it physically cannot "
    "aim for you. Full ESP suite (players, NPCs, animals, world, raid), "
    "radar, Bright Night, admin flags and debug camera. The safest config "
    "for everyday accounts."
)

LEGIT_TIERS = [
    ("1 Day", 1, 600),
    ("1 Week", 7, 2000),
    ("1 Month", 30, 3500),
]


def main():
    with app.app_context():
        # -- Full build: update the existing main Rust product ---------------
        full = Product.query.filter_by(slug="rust-external-private").first()
        if full is None:
            print("ERROR: rust-external-private not found — run against the "
                  "database that already has your products.")
            return 1
        full.name = "BEAZT Rust External"
        full.features_text = FULL_FEATURES
        full.description = FULL_DESCRIPTION
        full.game = full.game or "Rust"
        full.video_url = full.video_url or "https://www.youtube.com/watch?v=2SlYtGIZni8"
        print("Updated:", full.name)

        # -- Legit build: create if missing ----------------------------------
        legit = Product.query.filter_by(slug="rust-beazt-legit").first()
        if legit is None:
            legit = Product(
                name="BEAZT Legit — Rust",
                slug="rust-beazt-legit",
                description=LEGIT_DESCRIPTION,
                features_text=LEGIT_FEATURES,
                game="Rust",
                visibility="public",
                key_source="pool",
                status="undetected",
            )
            db.session.add(legit)
            print("Created: BEAZT Legit — Rust")
        else:
            legit.features_text = LEGIT_FEATURES
            legit.description = LEGIT_DESCRIPTION
            print("Updated: BEAZT Legit — Rust")
        db.session.flush()

        for label, days, pence in LEGIT_TIERS:
            exists = PricingTier.query.filter_by(
                product_id=legit.id, duration_days=days
            ).first()
            if not exists:
                db.session.add(PricingTier(
                    product_id=legit.id,
                    label=label,
                    duration_days=days,
                    price_pence=pence,
                ))
        db.session.commit()
        print("Tiers:", [(t.label, t.price_pence) for t in legit.tiers])
        print("Done.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
