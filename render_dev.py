#!/usr/bin/env python3
"""Development-only renderer: design.html -> entry.png via Playwright + system Chromium.

Not used at runtime; the graded runtime is main.py (stdlib only).
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent

def main(out: Path, width: int = 1024, height: int = 960) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium",
            args=["--no-sandbox", "--disable-dev-shm-usage", "--force-device-scale-factor=1"],
        )
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto((HERE / "design.html").as_uri())
        page.wait_for_timeout(300)
        el = page.locator("#page")
        el.screenshot(path=str(out), type="png")
        browser.close()

if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "entry.png"
    main(out)
    print(f"rendered -> {out}")
