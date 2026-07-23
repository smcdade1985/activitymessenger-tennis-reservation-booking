"""
Navigate directly to a slot's book_at URL to see what the confirmation UI looks like.
Using an existing slot (June 23 17:00) as a test target.
"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    # Use a known slot URL from the calendar exploration
    url = (
        "https://activitymessenger.com/org/4866/package/2592"
        "?d=2026-06-22&v=7d&p=availability"
        "&book_at=2026-06-23T17%3A00%3A00-0400"
    )
    print(f"Navigating to: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()

        await page.goto(url, wait_until="networkidle")
        await page.screenshot(path="booking_flow.png", full_page=True)

        # Dump the HTML to see what changed vs the plain calendar view
        html = await page.content()
        with open("booking_flow.html", "w", encoding="utf-8") as f:
            f.write(html)

        # Print all visible buttons
        buttons = await page.query_selector_all("button, input[type=submit], a.btn")
        print(f"\nVisible buttons/links ({len(buttons)}):")
        for btn in buttons:
            text = (await btn.inner_text()).strip()
            cls = await btn.get_attribute("class") or ""
            visible = await btn.is_visible()
            print(f"  visible={visible} class={cls!r} text={text!r}")

        print("\nKeeping browser open 30s...")
        await asyncio.sleep(30)
        await browser.close()

asyncio.run(main())
