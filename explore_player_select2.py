"""
Explore the 'Choisir un joueur' UI on a June 23 17:00 slot.
Clicks Réserver, inspects the player selection panel, then CLEARS CART
WITHOUT completing checkout — so the slot is NOT permanently booked.
"""
import asyncio
from playwright.async_api import async_playwright

SECOND_PLAYER = "player@example.com"
BASE_URL = "https://activitymessenger.com"

async def clear_cart(page):
    await page.goto(f"{BASE_URL}/org/4866/checkout", wait_until="networkidle")
    vider = page.locator("button:has-text('Vider le panier')").first
    try:
        await vider.wait_for(state="visible", timeout=3_000)
        await vider.click()
        await page.wait_for_load_state("networkidle")
        print("  Cart cleared")
    except Exception:
        print("  Cart already empty")

async def main():
    # June 23 17:00 — fresh slot, not used in tests
    url = (
        f"{BASE_URL}/org/4866/package/2592"
        "?d=2026-06-23&v=7d&p=availability&book_at=2026-06-23T17%3A00%3A00-0400"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()

        # Clear any stale cart first
        print("Clearing stale cart…")
        await clear_cart(page)

        # Navigate to slot
        print(f"Loading slot URL…")
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await page.screenshot(path="explore2_01_slot.png", full_page=True)

        # Click Réserver
        reserver = page.locator("button", has_text="Réserver").first
        try:
            await reserver.wait_for(state="visible", timeout=10_000)
        except Exception:
            print("ERROR: Réserver not found")
            await page.screenshot(path="explore2_error.png", full_page=True)
            content = await page.content()
            with open("explore2_page.html", "w", encoding="utf-8") as f:
                f.write(content)
            await asyncio.sleep(20)
            await browser.close()
            return

        print("Clicking Réserver…")
        await reserver.click()
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)
        await page.screenshot(path="explore2_02_after_reserver.png", full_page=True)
        print("Saved explore2_02_after_reserver.png")

        # Save the HTML of the booking panel state
        content = await page.content()
        with open("explore2_booking_panel.html", "w", encoding="utf-8") as f:
            f.write(content)
        print("Saved explore2_booking_panel.html")

        # Look for "Choisir un joueur" button
        choisir = page.locator(
            "button:has-text('Choisir'), a:has-text('Choisir')"
        ).first
        try:
            await choisir.wait_for(state="visible", timeout=8_000)
            choisir_text = await choisir.inner_text()
            print(f"Found: {choisir_text!r} — clicking…")
            await choisir.click()
            await asyncio.sleep(2)
            await page.screenshot(path="explore2_03_player_modal.png", full_page=True)
            print("Saved explore2_03_player_modal.png")

            # Save HTML of the modal
            content = await page.content()
            with open("explore2_modal.html", "w", encoding="utf-8") as f:
                f.write(content)
            print("Saved explore2_modal.html")

            # Print all visible inputs
            inputs = await page.query_selector_all("input")
            print(f"\nInputs after clicking Choisir ({len(inputs)}):")
            for inp in inputs:
                if await inp.is_visible():
                    t = await inp.get_attribute("type") or "text"
                    ph = await inp.get_attribute("placeholder") or ""
                    cls = (await inp.get_attribute("class") or "")[:60]
                    name = await inp.get_attribute("name") or ""
                    print(f"  type={t!r} placeholder={ph!r} name={name!r} class={cls!r}")

            # Try to type in any visible text input
            text_input = page.locator(
                "input[type=text], input[type=email], input[type=search], input:not([type])"
            ).first
            try:
                await text_input.wait_for(state="visible", timeout=3_000)
                print(f"\nTyping '{SECOND_PLAYER}' into input…")
                await text_input.fill(SECOND_PLAYER)
                await asyncio.sleep(2)
                await page.screenshot(path="explore2_04_typed.png", full_page=True)
                print("Saved explore2_04_typed.png")

                # Print visible list items / buttons after typing
                items = await page.query_selector_all("li, .list-group-item, [role=option]")
                visible_items = []
                for item in items:
                    if await item.is_visible():
                        text = (await item.inner_text()).strip()
                        if text and "arnaud" in text.lower():
                            visible_items.append(text)
                print(f"\nDropdown items matching 'arnaud': {visible_items}")

                # Also check all visible list items
                all_items = []
                for item in items:
                    if await item.is_visible():
                        text = (await item.inner_text()).strip()
                        if text:
                            all_items.append(text[:80])
                if all_items:
                    print(f"All visible list items: {all_items[:10]}")

            except Exception as e:
                print(f"No text input visible: {e}")

        except Exception as e:
            print(f"No 'Choisir' button found after Réserver: {e}")
            # Print all visible buttons
            btns = await page.query_selector_all("button")
            print("\nAll visible buttons:")
            for btn in btns:
                if await btn.is_visible():
                    text = (await btn.inner_text()).strip()
                    if text:
                        print(f"  {text!r}")

        print("\nClearing cart before closing (no permanent booking)…")
        await clear_cart(page)
        print("Done. Closing browser.")
        await browser.close()

asyncio.run(main())
