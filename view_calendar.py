import asyncio
from datetime import date, timedelta
from playwright.async_api import async_playwright

async def main():
    target_date = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
    url = f"https://activitymessenger.com/org/4866/package/2592?d={target_date}&v=7d&p=availability"
    print(f"Navigating to: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()

        await page.goto(url, wait_until="networkidle")
        await page.screenshot(path="calendar.png", full_page=True)
        print("Screenshot saved to calendar.png")

        print("Keeping browser open for 60 seconds...")
        await asyncio.sleep(60)

        await browser.close()

asyncio.run(main())
