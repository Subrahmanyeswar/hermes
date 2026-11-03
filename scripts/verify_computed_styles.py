import json
import time
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

sys.stdout.reconfigure(encoding='utf-8')

from tools.browser_tools import (
    BrowserOpenPreviewTool,
    BrowserSetViewportTool,
    BrowserCheckLayoutTool,
    BrowserCheckAccessibilityTool,
    BrowserCheckImagesTool,
    get_browser_manager,
    _run_async,
)

ws_dir = Path(r"C:\Users\SUBBU\Downloads\HERMES_FINAL_REVIEW_DEMO").resolve()

def inspect_computed_styles():
    print("=" * 70)
    print("AURELION COMPUTED STYLES & VISUAL QUALITY CDP INSPECTION")
    print("=" * 70)
    
    manager = get_browser_manager()
    open_tool = BrowserOpenPreviewTool(manager)
    res_open = open_tool.execute({"directory": str(ws_dir), "path": "index.html"})
    print("Preview server & browser launched:", res_open.success)
    time.sleep(2)

    # Set 1440x900 viewport
    vp_tool = BrowserSetViewportTool(manager)
    vp_tool.execute({"width": 1440, "height": 900})
    time.sleep(1)

    eval_script = """
    (() => {
        const getStyles = (selector) => {
            const el = document.querySelector(selector);
            if (!el) return null;
            const cs = window.getComputedStyle(el);
            return {
                tagName: el.tagName,
                className: el.className,
                color: cs.color,
                backgroundColor: cs.backgroundColor,
                fontFamily: cs.fontFamily,
                fontSize: cs.fontSize,
                fontWeight: cs.fontWeight,
                textDecorationLine: cs.textDecorationLine,
                textDecoration: cs.textDecoration,
                display: cs.display,
                position: cs.position,
                zIndex: cs.zIndex,
                boxShadow: cs.boxShadow,
                borderRadius: cs.borderRadius,
                border: cs.border,
                width: cs.width,
                height: cs.height,
                padding: cs.padding,
                margin: cs.margin
            };
        };

        const checks = {
            stylesheetLoaded: document.styleSheets.length > 0,
            styleSheetHref: Array.from(document.styleSheets).map(s => s.href),
            body: getStyles('body'),
            header: getStyles('.site-header'),
            navigation: getStyles('.nav-container'),
            navLinks: getStyles('.nav-links'),
            brandLogo: getStyles('.brand-logo'),
            brandLogoTextDecorationLine: window.getComputedStyle(document.querySelector('.brand-logo')).textDecorationLine,
            brandLogoColor: window.getComputedStyle(document.querySelector('.brand-logo')).color,
            hero: getStyles('.hero-section'),
            heroTitle: getStyles('.hero-title'),
            heroBadge: getStyles('.badge-gold'),
            primaryButton: getStyles('.btn-gold'),
            outlineButton: getStyles('.btn-outline'),
            glassButton: getStyles('.btn-glass'),
            modelsGrid: getStyles('.models-grid'),
            modelCard: getStyles('.model-card'),
            viewHome: getStyles('#view-home'),
            viewModels: getStyles('#view-models'),
            footer: getStyles('.site-footer'),
            horizontalOverflowDesktop: document.documentElement.scrollWidth > window.innerWidth,
            docScrollWidth: document.documentElement.scrollWidth,
            windowInnerWidth: window.innerWidth
        };

        return checks;
    })()
    """

    eval_res = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
        "expression": eval_script,
        "returnByValue": True
    }))

    style_data = eval_res.get("result", {}).get("value", {})
    print("\n[DESKTOP 1440px COMPUTED STYLES VERIFICATION]:")
    print(f"  Stylesheets loaded count: {len(style_data.get('styleSheetHref', []))}")
    print(f"  Stylesheets: {style_data.get('styleSheetHref')}")
    print(f"  Brand Logo Text Decoration Line: '{style_data.get('brandLogoTextDecorationLine')}' (Expected: 'none')")
    print(f"  Brand Logo Color: {style_data.get('brandLogoColor')} (Expected: rgb(255, 255, 255))")
    print(f"  Body Font Family: {style_data.get('body', {}).get('fontFamily')}")
    print(f"  Body Background Color: {style_data.get('body', {}).get('backgroundColor')}")
    print(f"  Header Position: {style_data.get('header', {}).get('position')}, Z-Index: {style_data.get('header', {}).get('zIndex')}")
    print(f"  Hero Title Font: {style_data.get('heroTitle', {}).get('fontFamily')}, Font Size: {style_data.get('heroTitle', {}).get('fontSize')}")
    print(f"  Primary Button Background: {style_data.get('primaryButton', {}).get('backgroundColor')}, Color: {style_data.get('primaryButton', {}).get('color')}")
    print(f"  Desktop Horizontal Overflow: {style_data.get('horizontalOverflowDesktop')} (scrollWidth={style_data.get('docScrollWidth')}px, innerWidth={style_data.get('windowInnerWidth')}px)")

    # Test Mobile 375px
    print("\n[MOBILE 375px VIEWPORT INSPECTION]:")
    vp_tool.execute({"width": 375, "height": 812, "is_mobile": True})
    time.sleep(1)

    eval_mobile = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
        "expression": """
        (() => {
            return {
                docScrollWidth: document.documentElement.scrollWidth,
                windowInnerWidth: window.innerWidth,
                horizontalOverflowMobile: document.documentElement.scrollWidth > window.innerWidth,
                mobileMenuBtnDisplay: window.getComputedStyle(document.querySelector('.mobile-menu-btn')).display,
                mainNavDisplay: window.getComputedStyle(document.querySelector('.main-nav')).display
            };
        })()
        """,
        "returnByValue": True
    }))
    mobile_data = eval_mobile.get("result", {}).get("value", {})
    print(f"  Mobile Scroll Width: {mobile_data.get('docScrollWidth')}px vs Window Inner Width: {mobile_data.get('windowInnerWidth')}px")
    print(f"  Mobile Horizontal Overflow: {mobile_data.get('horizontalOverflowMobile')} (MUST BE FALSE)")
    print(f"  Mobile Menu Button Display: {mobile_data.get('mobileMenuBtnDisplay')} (Expected: 'flex')")
    print(f"  Main Nav Display: {mobile_data.get('mainNavDisplay')} (Expected: 'none')")

    # Run Automated Layout Check across viewports
    print("\n[AUTOMATED MULTI-VIEWPORT LAYOUT CHECK]:")
    layout_tool = BrowserCheckLayoutTool(manager)
    layout_res = layout_tool.execute({})
    print("  Layout Check Success:", layout_res.success)
    print("  Layout Output:", layout_res.output)

    # Run Automated Image Integrity Check
    print("\n[AUTOMATED IMAGE INTEGRITY CHECK]:")
    img_tool = BrowserCheckImagesTool(manager)
    img_res = img_tool.execute({"scroll_first": True})
    print("  Image Check Success:", img_res.success)
    print("  Image Output:", img_res.output)

    combined_results = {
        "desktop_styles": style_data,
        "mobile_styles": mobile_data,
        "layout_check": {"success": layout_res.success, "output": layout_res.output},
        "image_check": {"success": img_res.success, "output": img_res.output}
    }

    out_file = ws_dir / "CSS_COMPUTED_STYLES_EVIDENCE.json"
    out_file.write_text(json.dumps(combined_results, indent=2), encoding="utf-8")
    print(f"\nAll computed styles and layout evidence written to: {out_file}")

    return combined_results

if __name__ == "__main__":
    inspect_computed_styles()
