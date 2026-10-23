"""Render the doc images that cannot be screenshots of the app: the architecture and decision-loop
diagrams (SVG sources in docs/images) and the article cover (docs/images/cover.html), to PNG.

    uv run --no-project --with playwright python scripts/render_doc_images.py
"""
import asyncio
from pathlib import Path

IMG = Path(__file__).resolve().parents[1] / "docs" / "images"
JOBS = [  # source, output, width, height
    ("architecture.svg", "architecture.png", 1600, 1000),
    ("decision-loop.svg", "decision-loop.png", 1600, 720),
    ("cover.html", "cover.png", 1600, 900),
]


async def main() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge")
        for src, out, w, h in JOBS:
            path = IMG / src
            if not path.exists():
                print("missing", src)
                continue
            page = await browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
            await page.goto(path.as_uri())
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(IMG / out), clip={"x": 0, "y": 0, "width": w, "height": h})
            await page.close()
            print("saved", out)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
