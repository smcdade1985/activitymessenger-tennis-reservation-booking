import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state="auth.json")
        page = await ctx.new_page()
        await page.goto(
            "https://activitymessenger.com/org/4866/package/2590?d=2026-06-20&v=7d&p=availability",
            wait_until="networkidle"
        )
        await page.screenshot(path="court_2590_calendar.png", full_page=True)
        text = await page.evaluate("() => document.body.innerText")
        for line in text.split("\n"):
            line = line.strip()
            if line:
                print(line)
        await browser.close()

asyncio.run(main())
