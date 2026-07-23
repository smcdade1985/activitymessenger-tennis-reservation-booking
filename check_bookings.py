"""Check the user's current bookings."""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()

        await page.goto("https://activitymessenger.com/org/4866/client", wait_until="networkidle")
        await page.screenshot(path="my_bookings.png", full_page=True)

        html = await page.content()
        with open("my_bookings.html", "w", encoding="utf-8") as f:
            f.write(html)

        print("Saved my_bookings.png and my_bookings.html")
        await asyncio.sleep(20)
        await browser.close()

asyncio.run(main())
