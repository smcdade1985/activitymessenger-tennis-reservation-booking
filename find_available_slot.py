"""Find any currently-bookable slot to use as a test booking."""
import asyncio
from datetime import date
from playwright.async_api import async_playwright

async def main():
    today = date.today().strftime("%Y-%m-%d")
    url = f"https://activitymessenger.com/org/4866/package/2592?d={today}&v=7d&p=availability"
    print(f"Loading current week: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()

        await page.goto(url, wait_until="networkidle")
        await page.screenshot(path="current_week.png", full_page=True)

        # Find all mc-event links and their styles
        slots = await page.query_selector_all("a.mc-event")
        print(f"\nFound {len(slots)} slots:")
        for slot in slots:
            href = await slot.get_attribute("href") or ""
            style = await slot.get_attribute("style") or ""
            text = (await slot.inner_text()).strip().replace("\n", " | ")
            bookable = "cursor: default" not in style
            print(f"  {'BOOKABLE' if bookable else 'gray   '} | {text} | {href.split('book_at=')[-1]}")

        await asyncio.sleep(20)
        await browser.close()

asyncio.run(main())
