"""
Probes Jacques Viger (package 2592) for the 2026-06-25 11 AM slot.
First attempt at 9:30:30 PM tonight; retries every 3 minutes, up to 10 attempts.
Stops early if the slot is confirmed open.
Logs each attempt to opening_time_probe.log and opening_time_log.xlsx.
Sends a summary email when probing is complete (success or exhausted).
"""
import asyncio
import logging
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

try:
    import openpyxl
except ImportError:
    print("openpyxl not installed — run: pip install openpyxl")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL    = "https://activitymessenger.com"
PACKAGE_ID  = "2592"
TARGET_DATE = "2026-06-25"
TARGET_HOUR = "11:00:00"
TZ_OFFSET   = "-0400"

GMAIL_ADDRESS  = "your_email@gmail.com"
EXCEL_FILE     = "opening_time_log.xlsx"
EXCEL_HEADERS  = ["Attempt #", "Timestamp", "Date Checked", "Slot Available", "Notes"]

FIRST_RUN_HOUR   = 21   # 9 PM
FIRST_RUN_MINUTE = 30
FIRST_RUN_SECOND = 30
INTERVAL_MINUTES = 3
MAX_ATTEMPTS     = 11

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("opening_time_probe.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.info


# ── Email ─────────────────────────────────────────────────────────────────────
def send_notification(subject, body):
    try:
        from email_config import GMAIL_APP_PASSWORD
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"]    = GMAIL_ADDRESS
        msg["To"]      = GMAIL_ADDRESS
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        log("  Email sent.")
    except Exception as e:
        log(f"  Email failed: {e}")


# ── Excel ─────────────────────────────────────────────────────────────────────
def append_excel_row(attempt_num: int, ts: datetime, available: bool, notes: str):
    path = Path(EXCEL_FILE)
    if path.exists():
        wb = openpyxl.load_workbook(path)
        ws = wb.active
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Opening Time Log"
        ws.append(EXCEL_HEADERS)
    ws.append([
        attempt_num,
        ts.strftime("%Y-%m-%d %H:%M:%S"),
        TARGET_DATE,
        "Yes" if available else "No",
        notes,
    ])
    wb.save(path)
    log(f"  Excel row appended (attempt #{attempt_num}, available={available}).")


# ── Cart clear ────────────────────────────────────────────────────────────────
async def clear_cart(page):
    await page.goto(f"{BASE_URL}/org/4866/checkout", wait_until="networkidle")
    vider = page.locator("button:has-text('Vider le panier')").first
    try:
        await vider.wait_for(state="visible", timeout=3_000)
        await vider.click()
        await page.wait_for_load_state("networkidle")
        log("  Cart cleared.")
    except Exception:
        log("  Cart already empty.")


# ── Single probe ──────────────────────────────────────────────────────────────
async def probe_slot(page, attempt_num: int) -> tuple[bool, datetime | None]:
    now  = datetime.now()
    hhmm = now.strftime("%H%M")
    log(f"--- Attempt #{attempt_num} at {now.strftime('%H:%M:%S')} ---")

    book_at_enc = quote(f"{TARGET_DATE}T{TARGET_HOUR}{TZ_OFFSET}", safe="")
    url = (
        f"{BASE_URL}/org/4866/package/{PACKAGE_ID}"
        f"?d={TARGET_DATE}&v=7d&p=availability&book_at={book_at_enc}"
    )
    log(f"  URL: {url}")

    notes    = ""
    available = False

    try:
        await page.goto(url, wait_until="networkidle")
        await page.screenshot(path=f"probe_{hhmm}_before.png", full_page=True)

        # Step 1: check Réserver button is present
        reserver = page.locator("button", has_text="Réserver").first
        try:
            await reserver.wait_for(state="visible", timeout=8_000)
            log("  'Réserver' found — clicking to confirm slot is truly open…")
        except Exception:
            notes = "Réserver button not found"
            log(f"  Not yet open — {notes}.")
            append_excel_row(attempt_num, now, False, notes)
            return False, None

        # Step 2: click it and wait for 'Choisir un joueur' to confirm server accepts it
        await reserver.click()
        await asyncio.sleep(2)
        await page.screenshot(path=f"probe_{hhmm}_after.png", full_page=True)

        choisir = page.locator("button:has-text('Choisir un joueur')").first
        try:
            await choisir.wait_for(state="visible", timeout=5_000)
            available = True
            notes = "Réserver clicked and cart opened — slot confirmed open"
            log(f"  SLOT OPEN — cart panel appeared, slot is genuinely available.")
        except Exception:
            notes = "Réserver clicked but cart did not open — slot not open yet"
            log(f"  Not yet open — Réserver click rejected by server.")

    except Exception as e:
        notes = f"Page load error: {e}"
        log(f"  ERROR: {notes}")

    # Always clear the cart so we don't leave a stale item
    await clear_cart(page)

    append_excel_row(attempt_num, now, available, notes)
    return available, (now if available else None)


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    log("=" * 60)
    log("Opening-time probe starting")
    log(f"  Target : Jacques Viger (package {PACKAGE_ID})")
    log(f"  Date   : {TARGET_DATE}  Slot: {TARGET_HOUR[:5]}")
    log(f"  Interval: every {INTERVAL_MINUTES} min, first attempt at "
        f"{FIRST_RUN_HOUR:02d}:{FIRST_RUN_MINUTE:02d}:{FIRST_RUN_SECOND:02d}")

    first_run = datetime.now().replace(
        hour=FIRST_RUN_HOUR,
        minute=FIRST_RUN_MINUTE,
        second=FIRST_RUN_SECOND,
        microsecond=0,
    )

    now = datetime.now()
    if first_run > now:
        wait_secs = (first_run - now).total_seconds()
        log(f"Sleeping {wait_secs:.0f}s until first attempt at "
            f"{first_run.strftime('%H:%M:%S')}…")
        await asyncio.sleep(wait_secs)
    else:
        log("First run time already passed — starting immediately.")

    async with async_playwright() as p:
        browser  = await p.chromium.launch(headless=True)
        context  = await browser.new_context(storage_state="auth.json")
        page     = await context.new_page()

        attempt_num = 0
        next_run    = first_run
        opened_at   = None

        while attempt_num < MAX_ATTEMPTS:
            attempt_num += 1
            available, opened_at = await probe_slot(page, attempt_num)

            if available:
                break

            if attempt_num < MAX_ATTEMPTS:
                next_run  = next_run + timedelta(minutes=INTERVAL_MINUTES)
                wait_secs = (next_run - datetime.now()).total_seconds()
                if wait_secs > 0:
                    log(f"  Next attempt at {next_run.strftime('%H:%M:%S')} "
                        f"(in {wait_secs:.0f}s).")
                    await asyncio.sleep(wait_secs)

        await browser.close()

        if opened_at:
            ts = opened_at.strftime("%Y-%m-%d %H:%M:%S")
            log(f"SLOT OPENED at {ts} after {attempt_num} attempt(s).")
            send_notification(
                subject="Tennis slots just opened!",
                body=(
                    f"Jacques Viger 11 AM slot for {TARGET_DATE} is now open.\n\n"
                    f"Detected at: {ts}\n"
                    f"Attempt #:   {attempt_num} of {MAX_ATTEMPTS}\n\n"
                    f"Full probe history: opening_time_log.xlsx"
                ),
            )
        else:
            log(f"Probing complete — slot not confirmed open after {MAX_ATTEMPTS} attempts.")
            send_notification(
                subject="Tennis probe complete — slot not found",
                body=(
                    f"Probing finished after {MAX_ATTEMPTS} attempts "
                    f"(every {INTERVAL_MINUTES} min starting at "
                    f"{first_run.strftime('%H:%M:%S')}).\n\n"
                    f"Jacques Viger 11 AM slot for {TARGET_DATE} was NOT confirmed open.\n\n"
                    f"Full probe history: opening_time_log.xlsx"
                ),
            )

        log("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
