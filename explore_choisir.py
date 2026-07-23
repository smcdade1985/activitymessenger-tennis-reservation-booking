"""
Uses the existing booking (id=977012, June 21 21:00) that is missing a 2nd player.
Navigates to checkout, clicks 'Choisir les joueurs', explores the modal,
then selects the configured second player.
"""
import asyncio
from playwright.async_api import async_playwright

SECOND_PLAYER = "player@example.com"
BASE_URL = "https://activitymessenger.com"

async def dump_buttons(page, label):
    btns = await page.query_selector_all("button, a.btn, .btn")
    visible = []
    for b in btns:
        if await b.is_visible():
            text = (await b.inner_text()).strip()
            if text:
                visible.append(text[:80])
    print(f"\n[{label}] visible buttons: {visible}")

async def dump_inputs(page, label):
    inputs = await page.query_selector_all("input")
    print(f"\n[{label}] inputs:")
    for inp in inputs:
        if await inp.is_visible():
            t = await inp.get_attribute("type") or "text"
            ph = await inp.get_attribute("placeholder") or ""
            cls = (await inp.get_attribute("class") or "")[:60]
            print(f"  type={t!r} placeholder={ph!r} class={cls!r}")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()

        # ── Navigate to checkout page ─────────────────────────────────────────
        print("Going to checkout page…")
        await page.goto(f"{BASE_URL}/org/4866/checkout", wait_until="networkidle")
        await asyncio.sleep(2)
        await page.screenshot(path="choisir_01_checkout.png", full_page=True)
        await dump_buttons(page, "checkout")

        # ── Click 'Choisir les joueurs' link ──────────────────────────────────
        choisir_link = page.locator("a:has-text('Choisir les joueurs'), button:has-text('Choisir les joueurs')").first
        try:
            await choisir_link.wait_for(state="visible", timeout=5_000)
            href = await choisir_link.get_attribute("href")
            print(f"Found 'Choisir les joueurs' link, href={href!r}")
            await choisir_link.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
            await page.screenshot(path="choisir_02_after_click.png", full_page=True)
            print(f"Current URL: {page.url}")
            await dump_buttons(page, "after choisir les joueurs click")
            await dump_inputs(page, "after click")
        except Exception as e:
            print(f"No 'Choisir les joueurs' link: {e}")
            content = await page.content()
            with open("choisir_checkout.html", "w", encoding="utf-8") as f:
                f.write(content)
            print("Saved choisir_checkout.html")
            await asyncio.sleep(20)
            await browser.close()
            return

        # ── Look for booking panel that should now be open ────────────────────
        # The booking_id URL should have opened the panel for that booking
        # Try: look for "Choisir un joueur" button (the per-player selection)
        choisir_joueur = page.locator(
            "button:has-text('Choisir un joueur'), a:has-text('Choisir un joueur')"
        ).first
        try:
            await choisir_joueur.wait_for(state="visible", timeout=8_000)
            print("Found 'Choisir un joueur' — clicking…")
            await choisir_joueur.click()
            await asyncio.sleep(2)
            await page.screenshot(path="choisir_03_player_modal.png", full_page=True)
            print("Saved choisir_03_player_modal.png")
            await dump_inputs(page, "after Choisir un joueur")
            await dump_buttons(page, "after Choisir un joueur")

            # Save modal HTML
            content = await page.content()
            with open("choisir_modal.html", "w", encoding="utf-8") as f:
                f.write(content)
            print("Saved choisir_modal.html")

            # Type the email in the search input
            search = page.locator(
                "input[type=text], input[type=email], input[type=search], input:not([type])"
            ).first
            try:
                await search.wait_for(state="visible", timeout=5_000)
                print(f"Typing '{SECOND_PLAYER}'…")
                await search.fill(SECOND_PLAYER)
                await asyncio.sleep(2)
                await page.screenshot(path="choisir_04_typed.png", full_page=True)
                print("Saved choisir_04_typed.png")
                await dump_buttons(page, "after typing")

                # Also check for list items
                items = await page.query_selector_all("li, [role=option], .list-group-item")
                print(f"\nList items after typing:")
                for item in items:
                    if await item.is_visible():
                        text = (await item.inner_text()).strip()
                        if text:
                            print(f"  {text[:100]!r}")

            except Exception as e:
                print(f"No search input: {e}")

        except Exception as e:
            print(f"No 'Choisir un joueur' button: {e}")
            # Print what's on the page
            await dump_buttons(page, "current page")
            await dump_inputs(page, "current page")
            content = await page.content()
            with open("choisir_02_page.html", "w", encoding="utf-8") as f:
                f.write(content)
            print("Saved choisir_02_page.html")

        print("\nKeeping browser open 30s…")
        await asyncio.sleep(30)
        await browser.close()

asyncio.run(main())
