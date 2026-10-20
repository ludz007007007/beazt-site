"""
Hero Section Validation Script for BEAZT Website
Uses Playwright to capture screenshots and validate hero elements
"""
import asyncio
from playwright.async_api import async_playwright
import os

async def validate_hero_section():
    results = {
        "desktop": {},
        "mobile": {},
        "elements_found": [],
        "elements_missing": [],
        "errors": []
    }
    
    screenshots_dir = os.path.join(os.getcwd(), "validation_screensshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # === DESKTOP VALIDATION (1280x720) ===
        print("=" * 50)
        print("DESKTOP VALIDATION (1280x720)")
        print("=" * 50)
        
        context_desktop = await browser.new_context(viewport={"width": 1280, "height": 720})
        page_desktop = await context_desktop.new_page()
        
        try:
            await page_desktop.goto("http://localhost:5000/", wait_until="networkidle", timeout=30000)
            print("[OK] Page loaded successfully")
            
            # Take desktop screenshot
            desktop_screenshot = os.path.join(screenshots_dir, "hero_desktop_1280x720.png")
            await page_desktop.screenshot(path=desktop_screenshot, full_page=False)
            print(f"[OK] Desktop screenshot saved: {desktop_screenshot}")
            results["desktop"]["screenshot"] = desktop_screenshot
            
            # Validate hero elements
            hero_elements = {
                "BEAZT Headline": "h1, .hero-title, .brand-title, [class*='headline'], [class*='hero']",
                "Value Proposition": ".value-prop, .tagline, .hero-description, [class*='subtitle'], p",
                "Primary CTA (Get Access/Browse)": "button:has-text('Get Access'), button:has-text('Browse'), a:has-text('Get Access'), a:has-text('Browse'), .cta-primary",
                "Secondary CTA (Join Discord)": "a:has-text('Discord'), button:has-text('Discord'), .cta-secondary",
                "Status Pill": ".status, .pill, [class*='status'], [class*='pill']",
                "Pulsing Indicator": ".pulse, [class*='pulse'], .status-dot",
                "Stats Row": ".stats, [class*='stat'], .metrics, .counters",
                "Premium Background": ".hero, header, [class*='hero'], [class*='premium']",
                "Grid Pattern": "[class*='grid'], [class*='pattern'], .hero-bg"
            }
            
            for element_name, selector in hero_elements.items():
                try:
                    element = await page_desktop.query_selector(selector)
                    if element:
                        is_visible = await element.is_visible()
                        if is_visible:
                            print(f"[OK] {element_name}: Found and visible")
                            results["elements_found"].append(element_name)
                            results["desktop"][element_name] = "visible"
                        else:
                            print(f"[WARN] {element_name}: Element exists but not visible")
                            results["desktop"][element_name] = "hidden"
                    else:
                        print(f"[MISS] {element_name}: Not found")
                        results["elements_missing"].append(element_name)
                        results["desktop"][element_name] = "not_found"
                except Exception as e:
                    print(f"[ERR] {element_name}: {str(e)}")
                    results["errors"].append(f"{element_name}: {str(e)}")
                    results["desktop"][element_name] = f"error: {str(e)}"
            
            # Check for scroll animation (look for animation classes)
            animations = await page_desktop.query_selector_all("[class*='animate'], [class*='reveal'], [class*='fade'], [style*='animation']")
            if animations:
                print(f"[OK] Animation elements found: {len(animations)} elements")
                results["desktop"]["animations"] = f"{len(animations)} animation elements"
            else:
                print("[INFO] No obvious animation elements detected")
                results["desktop"]["animations"] = "none_detected"
                
        except Exception as e:
            print(f"[ERR] Desktop validation error: {str(e)}")
            results["errors"].append(f"Desktop: {str(e)}")
        
        await context_desktop.close()
        
        # === MOBILE VALIDATION (375px width) ===
        print("\n" + "=" * 50)
        print("MOBILE VALIDATION (375px width)")
        print("=" * 50)
        
        context_mobile = await browser.new_context(viewport={"width": 375, "height": 667})
        page_mobile = await context_mobile.new_page()
        
        try:
            await page_mobile.goto("http://localhost:5000/", wait_until="networkidle", timeout=30000)
            print("[OK] Mobile page loaded successfully")
            
            # Take mobile screenshot
            mobile_screenshot = os.path.join(screenshots_dir, "hero_mobile_375x667.png")
            await page_mobile.screenshot(path=mobile_screenshot, full_page=False)
            print(f"[OK] Mobile screenshot saved: {mobile_screenshot}")
            results["mobile"]["screenshot"] = mobile_screenshot
            
            # Check key elements on mobile
            mobile_elements = [
                "Headline visible on mobile",
                "CTA buttons accessible",
                "Stats visible",
                "Layout responsive"
            ]
            
            # Quick checks
            headline = await page_mobile.query_selector("h1, .hero-title, [class*='hero']")
            if headline:
                visible = await headline.is_visible()
                results["mobile"]["headline"] = "visible" if visible else "hidden"
                print(f"[OK] Headline visible on mobile: {visible}")
            
            cta_buttons = await page_mobile.query_selector_all("button, a.btn, .cta")
            results["mobile"]["cta_count"] = len(cta_buttons)
            print(f"[OK] CTA elements found: {len(cta_buttons)}")
            
            stats = await page_mobile.query_selector(".stats, [class*='stat']")
            results["mobile"]["stats_visible"] = await stats.is_visible() if stats else False
            print(f"[OK] Stats section: {'visible' if results['mobile']['stats_visible'] else 'not visible'}")
            
        except Exception as e:
            print(f"[ERR] Mobile validation error: {str(e)}")
            results["errors"].append(f"Mobile: {str(e)}")
        
        await context_mobile.close()
        await browser.close()
    
    return results

if __name__ == "__main__":
    print("Starting BEAZT Hero Section Validation...\n")
    results = asyncio.run(validate_hero_section())
    
    print("\n" + "=" * 50)
    print("VALIDATION SUMMARY")
    print("=" * 50)
    print(f"Elements Found: {len(results['elements_found'])}")
    print(f"Elements Missing: {len(results['elements_missing'])}")
    if results['elements_missing']:
        print("Missing Elements:")
        for elem in results['elements_missing']:
            print(f"  - {elem}")
    if results['errors']:
        print("Errors Encountered:")
        for err in results['errors']:
            print(f"  - {err}")
    
    print("\nScreenshots saved to:", os.path.join(os.getcwd(), "validation_screensshots"))
