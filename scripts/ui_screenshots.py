"""Capture dashboard screenshots for the README and article (docs/images/dashboard-*.png).

Needs the backend running (replay or live) on 127.0.0.1:8765, or uses the built-in demo story with --demo.
Run with a throwaway environment so playwright never enters requirements.txt:

    uv run --no-project --with playwright python scripts/ui_screenshots.py --demo

It drives the installed Microsoft Edge (channel msedge), so no browser download is needed.
"""
import argparse
import asyncio
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"
BASE = "http://127.0.0.1:8765/"

# (file, query, hash, seconds to wait after load, viewport)
SHOTS = [
    ("dashboard-now-too-close", "demo=1&theme=day", "", 19, (1440, 900)),
    ("dashboard-now-worked", "demo=1&theme=day", "", 37, (1440, 900)),
    ("dashboard-now-night", "demo=1&theme=night", "", 19, (1440, 900)),
    ("dashboard-break", "demo=1&theme=day", "", 96, (1440, 900)),
    ("dashboard-reflex", "demo=1&theme=night", "reflex", 60, (1440, 900)),
    ("dashboard-day", "demo=1&theme=day", "day", 70, (1440, 900)),
    ("dashboard-rulebook-contrast", "demo=1&theme=contrast", "rules", 112, (1440, 900)),
    ("dashboard-now-mobile", "demo=1&theme=day", "", 19, (390, 844)),
]


async def main(only: str | None) -> None:
    from playwright.async_api import async_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        # needs a Playwright release newer than the installed Edge
        browser = await p.chromium.launch(channel="msedge")
        jobs = [s for s in SHOTS if not only or only in s[0]]

        async def one(name, query, hash_, wait_s, vp):
            ctx = await browser.new_context(viewport={"width": vp[0], "height": vp[1]}, device_scale_factor=2)
            page = await ctx.new_page()
            await page.goto(f"{BASE}?{query}{'#' + hash_ if hash_ else ''}")
            await page.wait_for_timeout(int(wait_s * 1000))
            await page.screenshot(path=str(OUT / f"{name}.png"), full_page=vp[0] < 800)
            await ctx.close()
            print("saved", name)

        await asyncio.gather(*(one(*s) for s in jobs))
        await browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    asyncio.run(main(a.only))
