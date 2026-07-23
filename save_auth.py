import asyncio
import sys
from playwright.async_api import async_playwright

async def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "auth.json"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto("https://activitymessenger.com/org/4866/client")
        print("Browser open. You have 3 minutes to log in...")

        for remaining in range(180, 0, -10):
            print(f"  {remaining} seconds remaining...")
            await asyncio.sleep(10)

        print(f"Saving storage state to {out_path}...")
        await context.storage_state(path=out_path)
        print(f"Done! {out_path} saved.")

        await browser.close()

asyncio.run(main())
