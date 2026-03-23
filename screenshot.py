# ============================================================
# MID Ops Report Bot — Screenshot Generator
# ============================================================
# Converts HTML report to PNG using Playwright.

import asyncio
import tempfile
import os


async def html_to_png(html_content: str, output_path: str, width: int = 780):
    """Convert HTML string to PNG screenshot using Playwright."""
    from playwright.async_api import async_playwright

    # Write HTML to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html_content)
        html_path = f.name

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={"width": width, "height": 1200})
            await page.goto(f"file://{html_path}")
            await page.wait_for_timeout(500)
            height = await page.evaluate("document.body.scrollHeight")
            await page.set_viewport_size({"width": width, "height": height + 80})
            await page.screenshot(path=output_path, full_page=True)
            await browser.close()
    finally:
        os.unlink(html_path)

    return output_path


def generate_screenshot(html_content: str, output_path: str, width: int = 780) -> str:
    """Synchronous wrapper for html_to_png."""
    return asyncio.run(html_to_png(html_content, output_path, width))
