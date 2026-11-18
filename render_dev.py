#!/usr/bin/env python3
"""Development-only renderer: design.html -> entry.png via Playwright + system Chromium.

The graded runtime never imports this file and never touches a browser; main.py
just copies the committed entry.png. This helper exists so the committed image is
reproducible offline from its design source.

Usage: python3 render_dev.py [design.html] [entry.png]
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_CHROMIUM = "/usr/bin/chromium"
WIDTH = 1024
HEIGHT = 1024


def render(design: Path, out: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=DEFAULT_CHROMIUM,
            args=["--no-sandbox", "--disable-gpu", "--force-device-scale-factor=1",
                  "--font-render-hinting=none", "--disable-lcd-text", "--hide-scrollbars"],
        )
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT},
                                device_scale_factor=1)
        page.goto(design.resolve().as_uri())
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(250)  # let webfonts settle; page itself is static
        page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT},
                        animations="disabled")
        browser.close()


def main() -> int:
    design = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("design.html")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("entry.png")
    render(design, out)
    print(f"rendered {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
