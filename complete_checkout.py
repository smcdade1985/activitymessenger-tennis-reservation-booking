"""
Resumes and completes the pending checkout wizard (Vos informations → Paiement → Confirmation).
Used to finish the booking left mid-wizard from the previous test run.
"""
import asyncio
from playwright.async_api import async_playwright

BASE_URL = "https://activitymessenger.com"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state="auth.json")
        page = await ctx.new_page()

        await page.goto(f"{BASE_URL}/org/4866/checkout", wait_until="networkidle")
        await page.screenshot(path="resume_01_checkout.png", full_page=True)
        text = await page.evaluate("() => document.body.innerText")
        print(f"Page text snippet: {' '.join(text.split())[:300]!r}")

        # Walk through wizard steps
        for i in range(1, 6):
            await page.screenshot(path=f"resume_{i:02d}.png", full_page=True)
            text = await page.evaluate("() => document.body.innerText")
            snippet = " ".join(text.split())[:200]
            print(f"\nStep {i}: {snippet!r}")

            if any(kw in text for kw in ("Confirmation", "confirmée", "Merci", "réservation confirmée")):
                print("CONFIRMED — booking complete!")
                break

            btn = page.locator(
                "button:has-text('Suivant'), button:has-text('Confirmer'), "
                "button:has-text('Payer'), input[type=submit]"
            ).first
            try:
                await btn.wait_for(state="visible", timeout=5_000)
                btn_text = (await btn.inner_text()).strip()
                print(f"  Clicking {btn_text!r}…")
                await btn.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"  No nav button: {e}")
                break

        await browser.close()

asyncio.run(main())
