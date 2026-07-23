"""
Click Réserver on an available slot, then click 'Choisir un joueur'
to see how the player selection UI works.
"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    # Use the June 21 07:00 slot (available, used for earlier tests)
    url = (
        "https://activitymessenger.com/org/4866/package/2592"
        "?d=2026-06-21&v=7d&p=availability&book_at=2026-06-21T07%3A00%3A00-0400"
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()

        # Clear cart first
        await page.goto("https://activitymessenger.com/org/4866/checkout", wait_until="networkidle")
        try:
            vider = page.locator("button:has-text('Vider le panier')").first
            await vider.wait_for(state="visible", timeout=3_000)
            await vider.click()
            await page.wait_for_load_state("networkidle")
            print("Cart cleared")
        except Exception:
            print("Cart already empty")

        await page.goto(url, wait_until="networkidle")
        reserver = page.locator("button", has_text="Réserver").first
        await reserver.wait_for(state="visible", timeout=10_000)
        await reserver.click()
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        # Click "Choisir un joueur"
        choisir = page.locator("button:has-text('Choisir un joueur'), a:has-text('Choisir un joueur')").first
        await choisir.wait_for(state="visible", timeout=5_000)
        print("Clicking 'Choisir un joueur'…")
        await choisir.click()
        await asyncio.sleep(2)
        await page.screenshot(path="player_select.png", full_page=True)

        # Dump visible inputs / search fields
        inputs = await page.query_selector_all("input[type=text], input[type=search], input:not([type])")
        print(f"\nVisible inputs ({len(inputs)}):")
        for inp in inputs:
            if await inp.is_visible():
                placeholder = await inp.get_attribute("placeholder") or ""
                cls = await inp.get_attribute("class") or ""
                print(f"  placeholder={placeholder!r} class={cls!r}")

        print("\nKeeping browser open 30s…")
        await asyncio.sleep(30)
        await browser.close()

asyncio.run(main())
