import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()
        await page.goto("https://activitymessenger.com/org/4866/client", wait_until="networkidle")
        await page.get_by_role("tab", name="Réservations").click()
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(3)
        await page.screenshot(path="reservations.png", full_page=True)
        print("Saved reservations.png")
        await asyncio.sleep(20)
        await browser.close()

asyncio.run(main())
