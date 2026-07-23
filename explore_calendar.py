import asyncio
from datetime import date, timedelta
from playwright.async_api import async_playwright

async def main():
    target_date = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
    url = f"https://activitymessenger.com/org/4866/package/2592?d={target_date}&v=7d&p=availability"
    print(f"Target date: {target_date}")
    print(f"URL: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()

        await page.goto(url, wait_until="networkidle")
        await page.screenshot(path="explore.png", full_page=True)

        html = await page.content()
        with open("calendar.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved explore.png and calendar.html")

        # Print all clickable elements that might be time slots
        slots = await page.query_selector_all("button, a, [role='button'], [class*='slot'], [class*='time'], [class*='avail']")
        print(f"\nFound {len(slots)} candidate elements:")
        for el in slots:
            text = (await el.inner_text()).strip()
            cls = await el.get_attribute("class") or ""
            href = await el.get_attribute("href") or ""
            if text or "slot" in cls or "time" in cls or "avail" in cls:
                print(f"  tag={await el.evaluate('el => el.tagName')} class={cls!r} href={href!r} text={text!r}")

        print("\nKeeping browser open 30s for manual inspection...")
        await asyncio.sleep(30)
        await browser.close()

asyncio.run(main())
