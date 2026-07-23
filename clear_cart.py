"""Navigate to checkout and clear all cart items."""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()

        await page.goto("https://activitymessenger.com/org/4866/checkout", wait_until="networkidle")
        await page.screenshot(path="checkout_page.png", full_page=True)

        html = await page.content()
        with open("checkout.html", "w", encoding="utf-8") as f:
            f.write(html)

        # Print all buttons/links visible on the page
        btns = await page.query_selector_all("button, a")
        print(f"Found {len(btns)} buttons/links:")
        for btn in btns:
            text = (await btn.inner_text()).strip()
            cls = await btn.get_attribute("class") or ""
            visible = await btn.is_visible()
            if visible and (text or "close" in cls.lower()):
                print(f"  visible={visible} class={cls!r} text={text!r}")

        await asyncio.sleep(20)
        await browser.close()

asyncio.run(main())
