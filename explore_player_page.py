"""
Explores the 'Choisir les joueurs' UI using an existing booking (booking_id=977012).
This helps us understand how to automate player selection for a saved contact.
"""
import asyncio
from playwright.async_api import async_playwright

SECOND_PLAYER = "player@example.com"

async def dump_inputs(page, label):
    inputs = await page.query_selector_all("input")
    print(f"\n[{label}] inputs ({len(inputs)}):")
    for inp in inputs:
        if await inp.is_visible():
            t = await inp.get_attribute("type") or "text"
            ph = await inp.get_attribute("placeholder") or ""
            cls = await inp.get_attribute("class") or ""
            print(f"  type={t!r} placeholder={ph!r} class={cls[:60]!r}")

async def dump_buttons(page, label):
    btns = await page.query_selector_all("button, a.btn")
    print(f"\n[{label}] buttons ({len(btns)}):")
    for btn in btns:
        if await btn.is_visible():
            text = (await btn.inner_text()).strip()[:80]
            if text:
                print(f"  {text!r}")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()

        # ── Navigate to the existing booking's player-selection page ──────────
        url = (
            "https://activitymessenger.com/org/4866/package/2592"
            "?d=2026-06-21&v=4d&booking_id=977012"
        )
        print(f"Navigating to: {url}")
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(2)
        await page.screenshot(path="ps1_booking_page.png", full_page=True)
        await dump_buttons(page, "after nav")
        await dump_inputs(page, "after nav")

        # ── Look for Choisir un joueur button ─────────────────────────────────
        choisir = page.locator("button:has-text('Choisir'), a:has-text('Choisir')").first
        try:
            await choisir.wait_for(state="visible", timeout=5_000)
            text = await choisir.inner_text()
            print(f"\nFound button: {text!r} — clicking…")
            await choisir.click()
            await asyncio.sleep(2)
            await page.screenshot(path="ps2_after_choisir_click.png", full_page=True)
            await dump_inputs(page, "after choisir click")
            await dump_buttons(page, "after choisir click")
        except Exception as e:
            print(f"No 'Choisir' button found: {e}")
            # Check what's on the page
            content = await page.content()
            with open("ps1_page.html", "w", encoding="utf-8") as f:
                f.write(content)
            print("Saved HTML to ps1_page.html")
            await asyncio.sleep(30)
            await browser.close()
            return

        # ── Try typing in search field ─────────────────────────────────────────
        search = page.locator("input[type=text], input[type=email], input[type=search], input:not([type])").first
        try:
            await search.wait_for(state="visible", timeout=3_000)
            print(f"\nTyping email into search field…")
            await search.fill(SECOND_PLAYER)
            await asyncio.sleep(2)
            await page.screenshot(path="ps3_typed_email.png", full_page=True)
            await dump_buttons(page, "after typing email")

            # Try pressing Enter or clicking a result
            results = page.locator(
                "li:has-text('arnaud'), div:has-text('arnaud'), "
                "option:has-text('arnaud'), button:has-text('arnaud')"
            ).first
            try:
                await results.wait_for(state="visible", timeout=3_000)
                result_text = await results.inner_text()
                print(f"\nFound result: {result_text!r} — clicking…")
                await results.click()
                await asyncio.sleep(2)
                await page.screenshot(path="ps4_player_selected.png", full_page=True)
            except Exception:
                print("No dropdown result found, trying Enter key…")
                await search.press("Enter")
                await asyncio.sleep(2)
                await page.screenshot(path="ps4_after_enter.png", full_page=True)
                await dump_buttons(page, "after enter")

        except Exception as e:
            print(f"No search input found: {e}")
            content = await page.content()
            with open("ps2_page.html", "w", encoding="utf-8") as f:
                f.write(content)
            print("Saved HTML to ps2_page.html")

        print("\nKeeping browser open 30s for review…")
        await asyncio.sleep(30)
        await browser.close()

asyncio.run(main())
