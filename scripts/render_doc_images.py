"""Render the doc images that cannot be screenshots of the app, to PNG at 2x:

- architecture.png, decision-loop.png, results.png, reflex-gate.png: the last frame of the animated
  explainers in scripts/video_scenes.html, so the article and the video show the same diagrams;
- cover.png from docs/images/cover.html.

    uv run --no-project --with playwright python scripts/render_doc_images.py
"""
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "docs" / "images"
SCENES = ROOT / "scripts" / "video_scenes.html"
EXPLAINERS = {"arch": "architecture.png", "decide": "decision-loop.png", "results": "results.png",
              "pattern": "reflex-gate.png"}


async def main() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge")
        page = await browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2)
        for scene, out in EXPLAINERS.items():
            await page.goto(f"{SCENES.as_uri()}?scene={scene}&doc=1")
            await page.evaluate("setup({dur: 40, lead: 0, cues: [[0,1],[2,3],[4,5],[6,7],[8,9],[10,11]]})")
            await page.evaluate("render(39)")
            await page.evaluate("document.querySelectorAll('#pulse').forEach(e => e.style.opacity = 0)")
            await page.screenshot(path=str(IMG / out))
            print("saved", out)
        cover = await browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        await cover.goto((IMG / "cover.html").as_uri())
        await cover.wait_for_timeout(800)
        await cover.screenshot(path=str(IMG / "cover.png"))
        print("saved cover.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
