"""
Books tennis slots 8 days from today, trying courts and times in priority order,
for every account in ACCOUNTS (see that comment block for per-account overrides
like custom priority lists and weekday-restricted second players).
Run at 9:30:30 PM Sun–Fri via Windows Task Scheduler.
  - Monday 9:31 PM  → books Tuesday  8 days from today (next week)
  - Tuesday 9:31 PM → books Wednesday 8 days from today (next week)
  - Friday 9:31 PM  → books Saturday 8 days from today (next week)
  … and so on. Accounts without their own weekday_players default to Mon-Fri
  only, so the Friday run only actually books for accounts that opted into a
  Saturday slot.

Default booking priority (first available slot wins), used by any account that
doesn't set its own booking_priority/priority_override:
  1. Jacques Viger   (package 2592) at 11 AM
  2. Jacques Viger   (package 2592) at 10 AM
  3. Jacques Viger   (package 2592) at noon
  4. Roland Proulx   (package 2590) at 11 AM
  5. Roland Proulx   (package 2590) at 10 AM
  6. Roland Proulx   (package 2590) at noon
  7. De la Vérendrye (package 2434) at 11 AM
  If all of the above fail, log and email that no court was available.

Booking flow per court/time attempt:
  1. Navigate to book_at URL → slot panel opens
  2. Click Réserver → cart panel shows "Choisir un joueur"
  3. Click "Choisir un joueur" → modal opens
  4. Click "Choisir une personne ▼" → contact dropdown appears
  5. Click the matching contact entry → form auto-fills
  6. Click "Sauvegarder" → player saved, modal closes
  7. Click "Caisse de sortie" (waits for Vue to re-enable button before clicking)
  8. Walk through checkout wizard (Suivant × 2-3) to Confirmation
"""
import asyncio
import csv
import os
import random
import re
import sys
import logging
import smtplib
import math
import traceback
from email.mime.text import MIMEText
from datetime import date, datetime, timedelta
from urllib.parse import quote
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from zoneinfo import ZoneInfo

from local_config import GMAIL_ADDRESS, SHEET_SPREADSHEET_ID, KNOWN_PLAYERS, ACCOUNTS

# Log to both file and stdout so Task Scheduler captures results
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("booking.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.info

# ── Realistic User-Agent rotation ──────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]

VIEWPORT_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
]

# ── Human-like behavior helpers ─────────────────────────────────────────────

async def human_delay(min_ms=500, max_ms=2000):
    """Pause for a random duration to simulate human thinking/reading time."""
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)

async def human_type(page, selector, text):
    """Type text character by character with random delays and occasional typos."""
    locator = page.locator(selector).first
    await locator.click()
    await human_delay(200, 500)
    for char in text:
        await page.keyboard.type(char, delay=random.randint(50, 150))
        if random.random() < 0.05:  # 5% chance of a typo
            await page.keyboard.press("Backspace")
            await human_delay(200, 400)
            await page.keyboard.type(char, delay=random.randint(50, 150))

async def human_mouse_move_bezier(page, target_x, target_y, duration_ms=1000):
    """
    Move mouse in a natural curved Bezier path with acceleration/deceleration.
    This is the most realistic mouse movement pattern.
    """
    # Get current mouse position (default to 0,0 if not tracked)
    start_x, start_y = await page.evaluate("() => [window.mouseX || 0, window.mouseY || 0]")
    
    # Create random control point for natural curve
    control_x = start_x + random.uniform(-100, 100)
    control_y = start_y + random.uniform(-100, 100)
    
    steps = random.randint(15, 30)
    for i in range(steps + 1):
        t = i / steps
        # Quadratic Bezier curve formula
        x = (1-t)**2 * start_x + 2*(1-t)*t*control_x + t**2 * target_x
        y = (1-t)**2 * start_y + 2*(1-t)*t*control_y + t**2 * target_y
        
        # Add slight random jitter (humans aren't perfectly smooth)
        x += random.uniform(-2, 2)
        y += random.uniform(-2, 2)
        
        await page.mouse.move(x, y)
        await asyncio.sleep(duration_ms / steps / 1000)

async def human_click(page, locator_or_selector, **kwargs):
    """
    Move the mouse using Bezier curves to the element and click,
    simulating realistic human cursor movement.
    """
    if isinstance(locator_or_selector, str):
        locator = page.locator(locator_or_selector).first
    else:
        locator = locator_or_selector
        
    try:
        await locator.wait_for(state="visible", timeout=kwargs.get('timeout', 5000))
        box = await locator.bounding_box()
        if box:
            target_x = box['x'] + box['width']/2
            target_y = box['y'] + box['height']/2
            
            # Use Bezier curve movement
            await human_mouse_move_bezier(page, target_x, target_y, duration_ms=random.randint(800, 1500))
            await human_delay(100, 300)
            await locator.click(**kwargs)
        else:
            # Fallback if bounding box fails
            await locator.click(**kwargs)
    except Exception:
        # Ultimate fallback
        await locator.click(**kwargs)

async def human_scroll_to_element(page, locator):
    """
    Scroll to element with natural pauses, overshoot, and correction.
    Humans rarely scroll perfectly to the exact position on first try.
    """
    await locator.scroll_into_view_if_needed()
    
    # Add slight overshoot and correction (very human-like)
    await page.mouse.wheel(0, random.randint(50, 150))
    await human_delay(200, 400)
    await page.mouse.wheel(0, random.randint(-20, -50))
    await human_delay(100, 200)

# ── End human-like behavior helpers ──────────────────────────────────────────

BASE_URL            = "https://activitymessenger.com"
DAYS_AHEAD          = 8      # today + 8 → one week out, next day (Tue→Wed, Wed→Thu …)
RETRY_INTERVAL_SECS = 30     # wait between retry rounds if no slot found
RETRY_TOTAL_SECS    = 600    # give up after 10 minutes total

# Transient network resilience (dropped connections, slow DNS, momentary
# server hiccups) — distinct from RETRY_INTERVAL_SECS/RETRY_TOTAL_SECS above,
# which poll for the booking window to open. This is a short exponential
# backoff applied to individual page loads so one flaky request doesn't crash
# the whole account's run for the night. See with_network_retry() below.
NAV_TIMEOUT_MS          = 30_000  # per-attempt navigation timeout (Playwright's own default)
NETWORK_RETRY_ATTEMPTS  = 3
NETWORK_RETRY_BASE_SECS = 2       # backoff: 2s, 4s, ... (2 * 2**(attempt-1))

# One entry per login the script books for. Accounts run concurrently
# each night. To onboard a new account:
#   1. python save_auth.py auth_<label>.json   (log in as that person, 3 min window)
#   2. Append a dict below with their details.
# "is_owner": True only for Sean's own account. Sean is never one of the two
# players in anyone else's booking, so calendar events are ONLY created for
# is_owner accounts — no calendar event at all gets created for a booking Sean
# isn't part of. Every account's confirmation email always CC's Sean on
# success, in addition to CC'ing him on all failures (see failure_recipients).
#
# Optional per-account overrides:
#   "booking_priority" — a (court_name, package_id, hour_str) list to use
#       instead of the shared BOOKING_PRIORITY (e.g. same courts, different hour).
#       Acts as this account's default whenever a weekday doesn't specify its
#       own priority_override (see below).
#   "weekday_players" — {weekday_int: (second_player_email, second_player_name,
#       also_email_player_on_success, priority_override)}, where weekday_int is
#       0=Monday .. 6=Sunday, keyed on the TARGET date's weekday (not the run
#       date). When set, the account ONLY attempts a booking on the listed
#       weekdays (all other target dates are skipped — for accounts WITHOUT
#       weekday_players at all, the default is Mon-Fri only, matching the
#       original single-account behavior), and uses that weekday's player
#       instead of second_player_email/name. If also_email_player_on_success is
#       True, that player also gets the confirmation email when the booking
#       succeeds. priority_override is a (court_name, package_id, hour_str)
#       list used only for that weekday; pass None to fall back to this
#       account's "booking_priority" (or the shared BOOKING_PRIORITY if that
#       isn't set either).
#
# ACCOUNTS itself lives in local_config.py (gitignored — see that file for
# the actual account list) since it contains real names/emails.
ACCOUNT_REQUIRED_KEYS = {
    "label", "display_name", "auth_file",
    "second_player_email", "second_player_name", "notify_email", "is_owner",
}

# Time-of-day options, mapped to their (start, end) display labels. Covers
# every hourly start time the platform actually offers (07:00-21:00, verified
# against the live availability grid for all three courts) — not just the
# subset BOOKING_PRIORITY currently tries, so a Sheet's target_time can pick
# any real slot.
TIME_SLOTS = {
    "07:00:00": ("7:00 AM",  "8:00 AM"),
    "08:00:00": ("8:00 AM",  "9:00 AM"),
    "09:00:00": ("9:00 AM",  "10:00 AM"),
    "10:00:00": ("10:00 AM", "11:00 AM"),
    "11:00:00": ("11:00 AM", "12:00 PM"),
    "12:00:00": ("12:00 PM", "1:00 PM"),
    "13:00:00": ("1:00 PM",  "2:00 PM"),
    "14:00:00": ("2:00 PM",  "3:00 PM"),
    "15:00:00": ("3:00 PM",  "4:00 PM"),
    "16:00:00": ("4:00 PM",  "5:00 PM"),
    "17:00:00": ("5:00 PM",  "6:00 PM"),
    "18:00:00": ("6:00 PM",  "7:00 PM"),
    "19:00:00": ("7:00 PM",  "8:00 PM"),
    "20:00:00": ("8:00 PM",  "9:00 PM"),
    "21:00:00": ("9:00 PM",  "10:00 PM"),
}

# (court_name, package_id, hour) attempts tried in order; first available wins.
BOOKING_PRIORITY = [
    ("Jacques Viger",   "2592", "11:00:00"),
    ("Jacques Viger",   "2592", "10:00:00"),
    ("Jacques Viger",   "2592", "12:00:00"),
    ("Roland Proulx",   "2590", "11:00:00"),
    ("Roland Proulx",   "2590", "10:00:00"),
    ("Roland Proulx",   "2590", "12:00:00"),
    ("De la Vérendrye", "2434", "11:00:00"),
]

# ─ Optional Google Sheet config layer ──────────────────────────────────────
# Purely additive: an account only consults the Sheet if it sets "sheet_tab"
# below. If the Sheet can't be read for ANY reason (network, auth, missing
# tab, malformed rows), the account books exactly as it would with no Sheet
# at all. Each tab is a key/value table in range "<tab>!A2:B" with rows:
#   enabled       "TRUE" to let this run's booking proceed; anything else
#                 (including blank/missing) skips the booking and emails a
#                 "skipped — sheet disabled" notice. Not an error.
#   date_mode     "auto" (default) or "manual". Only gates target_date below —
#                 has NO effect on target_time or player_2, which apply the
#                 same way regardless of date_mode. "manual" requires
#                 target_date below to exactly equal today+DAYS_AHEAD (a
#                 sanity check, not a way to book a different day) and, if it
#                 matches, bypasses this account's weekday gate for that one
#                 run — the only way a weekend booking happens for an account
#                 with no matching weekday_players entry. In "auto" mode,
#                 target_date is never read at all.
#   target_date   Only read when date_mode=manual. Must equal today+DAYS_AHEAD
#                 exactly or the run is treated as invalid (no booking, email
#                 sent echoing the sheet contents).
#   target_time   Optional. Applied every run regardless of date_mode — NOT
#                 scoped to manual mode or to target_date, and does NOT
#                 auto-clear once the date it was meant for has passed. A
#                 value left over from a one-off override will keep silently
#                 applying every subsequent night until someone blanks the
#                 cell. Must be a key in TIME_SLOTS/ALLOWED_SLOTS if set.
#                 Substitutes this hour into every (court, package, hour)
#                 tuple of whichever priority list would otherwise be used,
#                 preserving court fallback order. Blank keeps the default.
#   player_2      Optional, same "applies regardless of date_mode, doesn't
#                 auto-clear" caveat as target_time above. Must be a key
#                 (case-insensitive) in KNOWN_PLAYERS below. Overrides the
#                 account's default/weekday_players player for this run.
#                 Blank keeps the default.
SHEET_SCOPES       = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SHEET_TIMEOUT_SECS = 8
# SHEET_SPREADSHEET_ID lives in local_config.py (gitignored).

ALLOWED_SLOTS = set(TIME_SLOTS.keys())

# Known player-2 contacts, keyed by email, so a Sheet's player_2 cell (a name
# picked from a Sheet dropdown) can be validated and mapped to an email
# without needing to parse the checkout page. NAME_TO_EMAIL is the reverse
# lookup, keyed by lowercased name, used to resolve what the Sheet actually
# contains. KNOWN_PLAYERS itself lives in local_config.py (gitignored).
NAME_TO_EMAIL = {name.lower(): email for email, name in KNOWN_PLAYERS.items()}

# ── override these for testing ──────────────────────────────────────────────
TEST_MODE    = False
TEST_BOOK_AT = ""
# ────────────────────────────────────────────────────────────────────────────


def get_tz_offset(target_date, hour_str):
    """
    Return Montreal's UTC offset for the given target date/time, e.g. '-0400'
    (EDT) or '-0500' (EST). Must be computed relative to target_date (not
    "now") — DAYS_AHEAD means target_date can fall on the other side of a DST
    transition from today, and the offset that's actually correct "now" would
    then be wrong for the booked date.
    """
    dt = datetime.strptime(f"{target_date}T{hour_str}", "%Y-%m-%dT%H:%M:%S")
    return dt.replace(tzinfo=ZoneInfo("America/Montreal")).strftime("%z")


# ── Email notification ───────────────────────────────────────────────────────
# GMAIL_ADDRESS lives in local_config.py (gitignored).

def send_notification(subject, body, to_email=GMAIL_ADDRESS):
    """to_email may be a single address or a list of addresses (all get the email)."""
    try:
        from email_config import GMAIL_APP_PASSWORD
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"]    = GMAIL_ADDRESS
        msg["To"]      = ", ".join(to_email) if isinstance(to_email, list) else to_email
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        log("  Email notification sent.")
    except Exception as e:
        log(f"  Email notification failed: {e}")


# ── Google Calendar ──────────────────────────────────────────────────────────

CALENDAR_TOKEN_FILE       = "token.json"
CALENDAR_SCOPES           = ["https://www.googleapis.com/auth/calendar.events"]
CALENDAR_TIMEZONE         = "America/Montreal"

# token.json's refresh token was granted both scopes together (see
# setup_calendar_auth.py). Any refresh must request the same combined set —
# requesting just one function's own scope subset causes Google to downscope
# the access token to that subset, and to_json() then persists the narrower
# scope list, silently breaking whichever function runs later in the same
# process using the still-unexpired, now-too-narrow token.
GOOGLE_TOKEN_SCOPES       = CALENDAR_SCOPES + SHEET_SCOPES

def create_calendar_event(target_date, court_name, court_number, hour_str, player_name,
                           owner_name):
    """
    Add a 1-hour 'Tennis – {court_name} Court {court_number}' event to Sean's
    primary calendar. Returns True on success, False on any failure (caller
    is responsible for alerting — this only logs).
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(CALENDAR_TOKEN_FILE, GOOGLE_TOKEN_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(CALENDAR_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())

        start_dt = datetime.strptime(hour_str, "%H:%M:%S")
        end_dt   = start_dt + timedelta(hours=1)

        court_label = f"{court_name} Court {court_number}" if court_number else court_name
        summary = f"Tennis – {court_label}"

        event = {
            "summary": summary,
            "description": f"Players: {owner_name} + {player_name}",
            "start": {"dateTime": f"{target_date}T{start_dt.strftime('%H:%M:%S')}", "timeZone": CALENDAR_TIMEZONE},
            "end":   {"dateTime": f"{target_date}T{end_dt.strftime('%H:%M:%S')}",   "timeZone": CALENDAR_TIMEZONE},
        }

        service = build("calendar", "v3", credentials=creds)
        created = service.events().insert(calendarId="primary", body=event).execute()
        log(f"  Calendar event created: {summary!r} on {target_date} "
            f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')} "
            f"(id={created.get('id')}).")
        return True
    except Exception as e:
        log(f"  Calendar event creation failed: {e}")
        return False


# ── Google Sheet config (optional) ───────────────────────────────────────────

def load_sheet_config(spreadsheet_id, tab_name):
    """
    Read key/value rows from range "<tab_name>!A2:B" of the given Sheet,
    reusing the Calendar OAuth token (token.json) with the added read-only
    Sheets scope. Returns a dict of {key: value} on success.

    Returns None on ANY failure (network, auth, missing tab, malformed
    response) — callers must treat None as "Sheet unavailable, use the
    hardcoded defaults exactly as if no Sheet existed."
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build
        import httplib2

        creds = Credentials.from_authorized_user_file(CALENDAR_TOKEN_FILE, GOOGLE_TOKEN_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(CALENDAR_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())

        http = AuthorizedHttp(creds, http=httplib2.Http(timeout=SHEET_TIMEOUT_SECS))
        service = build("sheets", "v4", http=http)
        # A1 notation requires sheet names with spaces/apostrophes/etc. to be
        # single-quoted, with embedded single quotes doubled (e.g. "Sean's
        # Bookings" -> 'Sean''s Bookings'!A2:B).
        quoted_tab = tab_name.replace("'", "''")
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=f"'{quoted_tab}'!A2:B"
        ).execute()

        rows = result.get("values", [])
        config = {
            row[0].strip(): row[1].strip()
            for row in rows if len(row) >= 2 and row[0].strip()
        }
        log(f"  [sheet:{tab_name}] Config loaded: {config}")
        return config
    except Exception as e:
        log(f"  [sheet:{tab_name}] WARNING: could not load sheet config: {e}")
        return None


def resolve_sheet_overrides(sheet_cfg, default_target_date):
    """
    Apply the enabled/date_mode/target_time/player_2 precedence rules to an
    already-loaded Sheet config dict. Pure function — no I/O.

    Returns (outcome, payload):
      ("disabled", None)                         — enabled != TRUE, not an error
      ("invalid", "<reason, echoing raw values>") — a present value failed validation
      ("ok", {"bypass_weekday_gate": bool, "override_hour": str|None,
              "override_email": str|None, "override_name": str|None})
    """
    if (sheet_cfg.get("enabled") or "").strip().upper() != "TRUE":
        return "disabled", None

    echo = ", ".join(f"{k}={v!r}" for k, v in sheet_cfg.items())

    date_mode = (sheet_cfg.get("date_mode") or "auto").strip().lower()
    bypass_weekday_gate = False
    if date_mode == "manual":
        raw_date = (sheet_cfg.get("target_date") or "").strip()
        if raw_date != default_target_date:
            return "invalid", (
                f"target_date {raw_date!r} does not match the expected "
                f"today+{DAYS_AHEAD} date ({default_target_date}). Sheet: {echo}"
            )
        bypass_weekday_gate = True
    elif date_mode != "auto":
        return "invalid", f"date_mode {date_mode!r} is not 'auto' or 'manual'. Sheet: {echo}"

    override_hour = None
    raw_time = (sheet_cfg.get("target_time") or "").strip()
    if raw_time:
        # Accept "H:MM", "HH:MM", or the canonical zero-padded "HH:MM:SS"
        # TIME_SLOTS key — whatever you'd naturally type/pick.
        parts = raw_time.split(":")
        try:
            h, m = int(parts[0]), int(parts[1])
            normalized_time = f"{h:02d}:{m:02d}:00"
        except (ValueError, IndexError):
            return "invalid", f"target_time {raw_time!r} is not a recognized slot. Sheet: {echo}"
        if normalized_time not in ALLOWED_SLOTS:
            return "invalid", f"target_time {raw_time!r} is not a recognized slot. Sheet: {echo}"
        override_hour = normalized_time

    override_email = None
    override_name  = None
    raw_player = (sheet_cfg.get("player_2") or "").strip()
    if raw_player:
        override_email = NAME_TO_EMAIL.get(raw_player.lower())
        if override_email is None:
            return "invalid", f"player_2 {raw_player!r} is not a known contact. Sheet: {echo}"
        override_name = KNOWN_PLAYERS[override_email]

    return "ok", {
        "bypass_weekday_gate": bypass_weekday_gate,
        "override_hour":       override_hour,
        "override_email":      override_email,
        "override_name":       override_name,
    }


# ── Booking history ──────────────────────────────────────────────────────────

HISTORY_FILE   = "booking_history.csv"
HISTORY_FIELDS = ["date_run", "target_date", "court_name", "court_number", "time_slot", "status", "notes"]

def log_booking_history(target_date, court_name, court_number, time_slot, status, notes,
                         account_label=None):
    import time
    if account_label:
        notes = f"[{account_label}] {notes}" if notes else f"[{account_label}]"
    for attempt in range(5):
        try:
            with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if f.tell() == 0:
                    writer.writerow(HISTORY_FIELDS)
                writer.writerow([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    target_date,
                    court_name or "",
                    court_number or "",
                    time_slot or "",
                    status,
                    notes,
                ])
            log(f"  Booking history row appended ({status}).")
            return
        except PermissionError:
            if attempt < 4:
                log(f"  booking_history.csv locked — retrying in 2s ({attempt + 1}/5)…")
                time.sleep(2)
            else:
                log(f"  Booking history append failed: file still locked after 5 attempts.")
        except Exception as e:
            log(f"  Booking history append failed: {e}")
            return


# ── Logging helpers ──────────────────────────────────────────────────────────

async def log_visible_buttons(page, label):
    btns = await page.query_selector_all("button")
    texts = []
    for b in btns:
        if await b.is_visible():
            t = (await b.inner_text()).strip().replace("\n", " ")
            if t:
                texts.append(repr(t))
    log(f"  [{label}] visible buttons: {', '.join(texts) if texts else '(none)'}")


async def log_page_text(page, label, max_chars=400):
    text = await page.evaluate("() => document.body.innerText")
    snippet = " ".join(text.split())[:max_chars]
    log(f"  [{label}] page text: {snippet!r}")


async def extract_court_number(page):
    """Look for a 'Terrain N' marker in the confirmation page text."""
    text = await page.evaluate("() => document.body.innerText")
    match = re.search(r"Terrain\s*(\d+)", text, re.IGNORECASE)
    return match.group(1) if match else None


# ─ Network resilience ───────────────────────────────────────────────────────

async def with_network_retry(coro_factory, tag, description, attempts=NETWORK_RETRY_ATTEMPTS):
    """
    Run an awaitable-producing callable with exponential backoff on failure.
    coro_factory is a zero-arg callable (e.g. a lambda) rather than a bare
    coroutine because a coroutine object can only be awaited once, and a
    retry needs a fresh one per attempt. Re-raises the last error once
    attempts are exhausted — callers/run_account's catch-all is what turns
    that into a logged, emailed failure instead of a silent crash.
    """
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            return await coro_factory()
        except Exception as e:
            last_err = e
            if attempt == attempts:
                break
            backoff = NETWORK_RETRY_BASE_SECS * (2 ** (attempt - 1))
            log(f"  [{tag}] {description} failed (attempt {attempt}/{attempts}): {e!r}. "
                f"Retrying in {backoff:.0f}s…")
            await asyncio.sleep(backoff)
    raise last_err


# ── Session check ────────────────────────────────────────────────────────────

async def check_session_valid(page, display_name, tag="session"):
    """
    Navigate to the logged-in homepage and look for the account name to
    confirm the session is still authenticated. Returns True if logged in,
    False if the session has expired.

    A navigation failure (network blip, DNS hiccup) is retried with backoff
    and, if still failing after that, propagates as an exception — this is
    deliberately distinct from returning False, since "the site was
    unreachable" and "the login expired" need different alerts/fixes.
    """
    await with_network_retry(
        lambda: page.goto(f"{BASE_URL}/org/4866/client", wait_until="networkidle", timeout=NAV_TIMEOUT_MS),
        tag, "Session-check navigation",
    )
    # Restrict to visible matches: the page also renders the name in a hidden
    # user-menu dropdown header that comes first in DOM order, and waiting for
    # that one to become visible would misreport a live session as expired.
    account_marker = page.locator(f"text={display_name} >> visible=true").first
    try:
        await account_marker.wait_for(state="visible", timeout=5_000)
        return True
    except Exception:
        return False


# ── Cart helpers ─────────────────────────────────────────────────────────────

async def clear_cart(page, tag="cart"):
    await with_network_retry(
        lambda: page.goto(f"{BASE_URL}/org/4866/checkout", wait_until="networkidle", timeout=NAV_TIMEOUT_MS),
        tag, "Cart-page navigation",
    )
    vider = page.locator("button:has-text('Vider le panier')").first
    try:
        await vider.wait_for(state="visible", timeout=3_000)
        log("  Cart had items — emptying…")
        await human_click(page, vider)
        await page.wait_for_load_state("networkidle")
        log("  Cart emptied.")
    except Exception:
        log("  Cart already empty.")


# ── Player selection ─────────────────────────────────────────────────────────

async def select_second_player(page, email, account_label="sean"):
    """
    In the cart panel (after Réserver):
      1. Click "Choisir un joueur" → modal opens
      2. Click "Choisir une personne ▼" → contact dropdown lists saved players
      3. Click the entry matching email → form auto-fills
      4. Click "Sauvegarder" → player saved, modal closes
    Returns (ok, reason): reason is None on success, else a short machine-
    readable code plus a human-readable detail, e.g.
    "no_contact_match: no dropdown entry contains 'x@y.com' — check
    KNOWN_PLAYERS/weekday_players against the account's actual saved
    contacts (site-side typos happen — see contacts list logged above)".
    """
    prefix = f"  [{account_label}] "

    # 1. Open the player modal
    choisir = page.locator("button:has-text('Choisir un joueur')").first
    try:
        await choisir.wait_for(state="visible", timeout=8_000)
        log(f"{prefix}'Choisir un joueur' found — clicking…")
        await human_click(page, choisir)
        await human_delay(1000, 2500)
        await page.screenshot(path=f"{account_label}_player_01_modal.png", full_page=True)
    except Exception as e:
        log(f"{prefix}ERROR: 'Choisir un joueur' not visible after 8 s: {e}")
        return False, "modal_not_found: 'Choisir un joueur' button never appeared"

    # 2. Open the saved-contacts dropdown
    choisir_personne = page.locator(
        "a:has-text('Choisir une personne'), button:has-text('Choisir une personne')"
    ).first
    dropdown_contacts = []
    try:
        await choisir_personne.wait_for(state="visible", timeout=5_000)
        log(f"{prefix}'Choisir une personne' dropdown found — clicking…")
        await human_click(page, choisir_personne)
        await human_delay(1000, 2500)
        await page.screenshot(path=f"{account_label}_player_02_dropdown.png", full_page=True)

        all_li = await page.query_selector_all("li, [role=option], .dropdown-item")
        for li in all_li:
            if await li.is_visible():
                t = (await li.inner_text()).strip().replace("\n", " ")
                if t:
                    dropdown_contacts.append(t[:100])
        log(f"{prefix}Dropdown contacts: {dropdown_contacts}")
    except Exception as e:
        log(f"{prefix}ERROR: 'Choisir une personne' not found: {e}")
        return False, "dropdown_not_found: 'Choisir une personne' control never appeared"

    # 3. Click the contact entry matching the target email
    entry = page.locator("li, [role=option], .dropdown-item, a").filter(has_text=email).first
    try:
        await entry.wait_for(state="visible", timeout=5_000)
        entry_text = (await entry.inner_text()).strip().replace("\n", " ")
        log(f"{prefix}Contact found: {entry_text!r} — clicking…")
        await human_click(page, entry)
        await human_delay(1000, 2500)
        await page.screenshot(path=f"{account_label}_player_03_selected.png", full_page=True)
    except Exception as e:
        log(f"{prefix}ERROR: No contact matching '{email}' in dropdown: {e}")
        await page.screenshot(path=f"{account_label}_player_03_error.png", full_page=True)
        return False, (
            f"no_contact_match: no dropdown entry contains '{email}' — saved contacts were "
            f"{dropdown_contacts}. Check KNOWN_PLAYERS/weekday_players against the account's "
            f"actual saved contact email (site-side typos happen)."
        )

    # 4. Save the selection
    sauvegarder = page.locator("button:has-text('Sauvegarder')").first
    try:
        await sauvegarder.wait_for(state="visible", timeout=5_000)
        log(f"{prefix}'Sauvegarder' found — clicking…")
        await human_click(page, sauvegarder)
        await human_delay(1000, 2500)
        await page.screenshot(path=f"{account_label}_player_04_saved.png", full_page=True)
        await log_visible_buttons(page, f"{account_label} after Sauvegarder")
        log(f"{prefix}Second player saved successfully.")
    except Exception as e:
        log(f"{prefix}ERROR: 'Sauvegarder' not found: {e}")
        await page.screenshot(path=f"{account_label}_player_04_error.png", full_page=True)
        return False, "save_failed: 'Sauvegarder' button never appeared after selecting contact"

    return True, None


# ── Per-court booking attempt ───────────────────────────────────────────────

async def try_book_court(page, court_name, package_id, book_at_enc, target_date,
                          second_player_email, account_label="sean"):
    """
    Attempt to book the slot at the given court/time (encoded in book_at_enc).
    Returns (booked, court_number, slot_open, fail_reason):
      - booked     : True if the booking completed successfully.
      - court_number: court number string from confirmation page, or None.
      - slot_open  : True if the booking window is open (Réserver button found),
                     False if the window is not yet open (no Réserver button).
      - fail_reason: None on success. Otherwise a short machine-readable code
                     ("taken", "payment_required", "player_select_failed: ...",
                     etc.) distinguishing *why* it failed — genuine contention
                     ("taken") vs. a config/site bug that needs fixing, so
                     failure emails/CSV notes don't collapse everything into
                     a misleading "not available".
    """
    tag = f"{account_label}/{court_name}"
    shot_prefix = f"{account_label}_{package_id}"

    url = (
        f"{BASE_URL}/org/4866/package/{package_id}"
        f"?d={target_date}&v=7d&p=availability&book_at={book_at_enc}"
    )
    log(f"  [{tag}] URL: {url}")

    # ── 1. Load the booking panel ─────────────────────────────────────────
    await with_network_retry(
        lambda: page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS),
        tag, "Court-page navigation",
    )
    await page.screenshot(path=f"{shot_prefix}_step1_loaded.png", full_page=True)
    await log_visible_buttons(page, f"{tag} step1")

    # ── 2. Find and click Réserver ───────────────────────────────────────
    reserver = page.locator("button", has_text="Réserver").first
    try:
        await reserver.wait_for(state="visible", timeout=10_000)
        log(f"  [{tag}] 'Réserver' found — clicking…")
    except Exception:
        log(f"  [{tag}] 'Réserver' not found — booking window not yet open.")
        await page.screenshot(path=f"{shot_prefix}_no_reserver.png", full_page=True)
        return False, None, False, "not_offered"

    await human_click(page, reserver)
    await page.wait_for_load_state("networkidle")
    await human_delay(1000, 2500)
    await page.screenshot(path=f"{shot_prefix}_step2_after_reserver.png", full_page=True)

    # Verify the Réserver click succeeded: "Choisir un joueur" must appear.
    # If the slot was just taken, an error notification appears instead.
    choisir_check = page.locator("button:has-text('Choisir un joueur')").first
    try:
        await choisir_check.wait_for(state="visible", timeout=5_000)
        log(f"  [{tag}] Réserver accepted — cart panel open.")
    except Exception:
        log(f"  [{tag}] Réserver rejected (slot unavailable or error).")
        await log_page_text(page, f"{tag}-reserver-rejected")
        return False, None, True, "taken"

    # ── 3. Select second player ───────────────────────────────────────────
    log(f"  [{tag}] Selecting second player…")
    player_ok, player_fail_reason = await select_second_player(page, second_player_email, account_label)
    if not player_ok:
        log(f"  [{tag}] Player selection failed ({player_fail_reason}) — clearing cart and giving up on this court.")
        await clear_cart(page, tag)
        return False, None, True, f"player_select_failed: {player_fail_reason}"

    # ─ 4. Caisse de sortie ───────────────────────────────────────────────
    await human_delay(1000, 2500)
    await log_visible_buttons(page, f"{tag} pre-caisse")
    caisse = page.locator("button", has_text="Caisse de sortie").first
    try:
        await caisse.wait_for(state="visible", timeout=8_000)
        # human_click waits for Vue to re-enable the button before firing
        log(f"  [{tag}] 'Caisse de sortie' found — waiting for it to be enabled…")
        await human_click(page, caisse, timeout=10_000)
        await page.wait_for_load_state("networkidle")
        await human_delay(1000, 2500)
        await page.screenshot(path=f"{shot_prefix}_step4_after_caisse.png", full_page=True)
        await log_page_text(page, f"{tag} after-caisse")
    except Exception as e:
        log(f"  [{tag}] ERROR: 'Caisse de sortie' not found: {e}")
        return False, None, True, f"caisse_unavailable: {e}"

    # ── 5. Walk the checkout wizard to Confirmation ───────────────────────
    # Steps: Panier d'achats → Vos informations → Paiement → Confirmation
    # Stop when no more Suivant/Confirmer button is visible.
    log(f"  [{tag}] Walking checkout wizard…")
    wizard_complete = False
    for step_num in range(1, 10):
        await page.screenshot(path=f"{shot_prefix}_checkout_{step_num}.png", full_page=True)
        log(f"  [{tag}] Checkout step {step_num}: URL={page.url}")
        await log_page_text(page, f"{tag}-checkout-{step_num}")

        nav_btn = page.locator(
            "button:visible:has-text('Suivant'), button:visible:has-text('Confirmer'), "
            "button:visible:has-text('Payer'), button:visible:has-text('Valider'), "
            "button:visible:has-text('Réserver maintenant'), "
            "input[type=submit]:visible"
        ).first
        try:
            await nav_btn.wait_for(state="visible", timeout=5_000)
            btn_text = (await nav_btn.inner_text()).strip()

            # A real (non-zero) charge is being requested — the bot has no
            # card on file and must never blindly submit a blank card form.
            # "Aucun paiement requis" is the site's own $0-due message; its
            # absence on a payment step means real money is being asked for.
            if "payer" in btn_text.lower():
                page_text_now = await page.evaluate("() => document.body.innerText")
                if "aucun paiement requis" not in page_text_now.lower():
                    log(f"  [{tag}] Payment step requires a real charge (no 'Aucun paiement "
                        f"requis') — refusing to submit a blank card form.")
                    await page.screenshot(path=f"{shot_prefix}_payment_required.png", full_page=True)
                    return False, None, True, "payment_required"

            log(f"  [{tag}] Clicking {btn_text!r}…")
            await human_click(page, nav_btn)
            await page.wait_for_load_state("networkidle")
            await human_delay(1000, 2500)
        except Exception:
            log(f"  [{tag}] No more navigation buttons — end of wizard.")
            await page.screenshot(path=f"{shot_prefix}_confirmed.png", full_page=True)
            await log_page_text(page, f"{tag}-final")
            wizard_complete = True
            break

    if not wizard_complete:
        log(f"  [{tag}] ERROR: checkout wizard loop exhausted without completing — booking not confirmed.")
        return False, None, True, "wizard_incomplete"

    # Verify we actually reached a confirmation page and didn't land on an error.
    page_text = await page.evaluate("() => document.body.innerText")
    if "réservation est confirmée" not in page_text.lower():
        log(f"  [{tag}] WARNING: wizard ended but no confirmation text found — booking may have failed.")
        await page.screenshot(path=f"{shot_prefix}_no_confirmation.png", full_page=True)
        return False, None, True, "no_confirmation"

    court_number = await extract_court_number(page)
    if court_number:
        log(f"  [{tag}] Extracted court number from confirmation page: {court_number}")
    else:
        log(f"  [{tag}] Could not extract a court number from confirmation page.")

    return True, court_number, True, None


# ── Per-account run ──────────────────────────────────────────────────────────

async def run_account(browser, account, target_date):
    """
    Run the full sentinel-wait + priority-sweep booking flow for a single
    account, in its own browser context, then send that account's
    owner their email confirmation and calendar invite.
    """
    label        = account["label"]
    auth_file    = account["auth_file"]
    notify_email = account["notify_email"]
    is_owner     = account["is_owner"]
    account_priority = account.get("booking_priority") or BOOKING_PRIORITY
    retry_total_secs = account.get("retry_total_secs", RETRY_TOTAL_SECS)

    # Failures are always also CC'd to Sean, even for other people's accounts,
    # so he has visibility without relying on each account owner to flag it.
    failure_recipients = notify_email if is_owner else [notify_email, GMAIL_ADDRESS]

    target_weekday = datetime.strptime(target_date, "%Y-%m-%d").weekday()
    weekday_name   = datetime.strptime(target_date, "%Y-%m-%d").strftime("%A")

    # ── Optional Sheet override (purely additive — see SHEET_* comment above
    # BOOKING_PRIORITY). Accounts without "sheet_tab" never touch any of this
    # and behave exactly as before.
    config_source        = "default"
    bypass_weekday_gate  = False
    override_hour        = None
    override_email       = None
    override_name        = None

    sheet_tab = account.get("sheet_tab")
    if sheet_tab:
        sheet_cfg = load_sheet_config(SHEET_SPREADSHEET_ID, sheet_tab)
        if sheet_cfg is None:
            log(f"[{label}] Sheet unavailable/unreadable — using hardcoded defaults.")
        else:
            outcome, payload = resolve_sheet_overrides(sheet_cfg, target_date)
            if outcome == "disabled":
                log(f"[{label}] Sheet ('{sheet_tab}') says disabled — skipping booking attempt.")
                send_notification(
                    subject=f"Tennis Booking ⏸️ Skipped — sheet disabled ({target_date})",
                    body=(
                        f"{account['display_name']}'s Sheet tab ('{sheet_tab}') does not have "
                        f"enabled=TRUE, so no booking attempt was made for {target_date}."
                    ),
                    to_email=failure_recipients,
                )
                log_booking_history(
                    target_date, None, None, None, "skipped",
                    "Sheet disabled", account_label=label,
                )
                return
            if outcome == "invalid":
                log(f"[{label}] Sheet ('{sheet_tab}') config invalid: {payload}")
                send_notification(
                    subject=f"Tennis Booking ⚠️ Invalid Sheet Config ({target_date})",
                    body=(
                        f"{account['display_name']}'s Sheet tab ('{sheet_tab}') has an invalid "
                        f"value — no booking attempt was made.\n\n{payload}"
                    ),
                    to_email=failure_recipients,
                )
                log_booking_history(
                    target_date, None, None, None, "fail",
                    f"Invalid sheet config: {payload}", account_label=label,
                )
                return
            # outcome == "ok"
            config_source       = "sheet"
            bypass_weekday_gate = payload["bypass_weekday_gate"]
            override_hour       = payload["override_hour"]
            override_email      = payload["override_email"]
            override_name       = payload["override_name"]

    # Some accounts only book on specific target-date weekdays, with a
    # different second player (and optionally a different priority list) per
    # weekday (see ACCOUNTS comment above). Accounts without "weekday_players"
    # default to the original Mon-Fri-only behavior. bypass_weekday_gate (set
    # only by an enabled Sheet with date_mode=manual) is the only way a
    # weekend/non-listed weekday proceeds instead of being skipped here.
    weekday_players = account.get("weekday_players")
    if weekday_players is not None:
        if target_weekday in weekday_players:
            player_email, player_name, also_notify_player, priority_override = weekday_players[target_weekday]
            priority_list = priority_override or account_priority
        elif bypass_weekday_gate:
            player_email = account["second_player_email"]
            player_name  = account["second_player_name"]
            also_notify_player = False
            priority_list = account_priority
        else:
            log(f"[{label}] Skipping — {target_date} ({weekday_name}) is not one of this "
                f"account's target weekdays.")
            log_booking_history(
                target_date, None, None, None, "skipped",
                f"{weekday_name} is not one of this account's target weekdays",
                account_label=label,
            )
            return
    else:
        if target_weekday < 5 or bypass_weekday_gate:
            player_email = account["second_player_email"]
            player_name  = account["second_player_name"]
            also_notify_player = False
            priority_list = account_priority
        else:
            log(f"[{label}] Skipping — {target_date} ({weekday_name}) — weekdays only.")
            log_booking_history(
                target_date, None, None, None, "skipped",
                f"{weekday_name} — weekdays only",
                account_label=label,
            )
            return

    # Sheet overrides win over weekday_players/base defaults, once resolved.
    if override_hour:
        priority_list = [(court, pkg, override_hour) for court, pkg, _ in priority_list]
    if override_email:
        player_email, player_name = override_email, override_name

    # Create browser context with realistic fingerprint
    context = await browser.new_context(
        storage_state=auth_file,
        user_agent=random.choice(USER_AGENTS),
        viewport=random.choice(VIEWPORT_SIZES),
        locale="fr-CA",  # Match Montreal location
        timezone_id="America/Montreal",
    )
    page = await context.new_page()
    
    # Apply stealth patches
    await Stealth().apply_stealth_async(page)
    
    # Add canvas and WebGL fingerprint spoofing
    await page.add_init_script("""
        // Canvas fingerprint spoofing - add tiny noise
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {
            const result = originalToDataURL.call(this, type);
            if (Math.random() > 0.5) {
                return result.replace('data:image/png;base64,', 'data:image/png;base64,' + 'A');
            }
            return result;
        };
        
        // WebGL vendor spoofing
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {
            const result = getParameter.call(this, param);
            if (param === 37445) return 'Intel Inc.';  // UNMASKED_VENDOR_WEBGL
            if (param === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
            return result;
        };
        
        // Track mouse position for realistic movement
        window.mouseX = 0;
        window.mouseY = 0;
        document.addEventListener('mousemove', (e) => {
            window.mouseX = e.clientX;
            window.mouseY = e.clientY;
        });
        
        // Add realistic localStorage
        localStorage.setItem('last_visit', new Date().toISOString());
        localStorage.setItem('view_count', String(Math.floor(Math.random() * 50) + 1));
    """)
    
    # Add realistic cookies
    await context.add_cookies([
        {
            "name": "session_pref",
            "value": "language=fr",
            "domain": "activitymessenger.com",
            "path": "/",
        }
    ])

    try:
        # Verify the saved session is still a valid, logged-in session
        log(f"--- [{label}] Step 0: verifying {auth_file} session ---")
        if not await check_session_valid(page, account["display_name"], label):
            log(f"[{label}] Session expired — {auth_file} is no longer authenticated. Skipping booking attempt.")
            send_notification(
                subject="Tennis Booking ⚠️ Session Expired",
                body=(
                    f"The saved login session ({auth_file}) has expired, so no booking "
                    f"attempt was made for {account['display_name']}.\n\n"
                    f"Please log in to activitymessenger.com manually and refresh {auth_file}."
                ),
                to_email=failure_recipients,
            )
            log_booking_history(
                target_date, None, None, None, "fail",
                f"{auth_file} session expired — no booking attempt made",
                account_label=label,
            )
            return
        log(f"[{label}] Session OK — proceeding with booking.")

        # Clear any stale cart before starting
        log(f"--- [{label}] Step 1: clearing stale cart ---")
        await clear_cart(page, label)

        # Each round walks the ENTIRE priority list in order, immediately
        # moving to the next court/time the moment one comes back without a
        # Réserver button — it never waits on a single court for the whole
        # retry budget. A missing Réserver only proves that specific slot
        # isn't offered right now (today's window may not be open yet, or
        # that court may just not carry that hour at all on this day of the
        # week) — it does not mean no other option in the list is bookable.
        # Once ANY option in a round comes back open (booked or taken), the
        # window is confirmed open — the round finishes sweeping the rest of
        # the list and then stops. Only when an ENTIRE round comes back empty
        # for every option does the script sleep RETRY_INTERVAL_SECS and try
        # the whole list again, up to RETRY_TOTAL_SECS total.
        booked_court        = None
        booked_court_number = None
        booked_start_label  = None
        booked_end_label    = None
        booked_hour_str     = None
        failed_attempts     = []  # plain "Court Label" strings, any reason — used in the success-path "Tried first" note
        blocked_attempts    = []  # (court, label, reason) for failures that are NOT plain contention — config/site bugs
        payment_attempts    = []  # (court, label, url) for slots that are open but require a real manual card payment
        start_time          = datetime.now()

        sentinel_name, _, sentinel_hour = priority_list[0]
        sentinel_label, _ = TIME_SLOTS[sentinel_hour]
        round_num = 0

        while True:
            round_num += 1
            window_open_this_round = False

            for idx, (court_name, package_id, hour_str) in enumerate(priority_list):
                start_label, end_label = TIME_SLOTS[hour_str]
                if TEST_MODE and TEST_BOOK_AT and round_num == 1 and idx == 0:
                    book_at_enc = TEST_BOOK_AT
                else:
                    book_at_enc = quote(f"{target_date}T{hour_str}{get_tz_offset(target_date, hour_str)}", safe="")

                log(f"--- [{label}] Round {round_num}: attempting {court_name} {start_label} ---")
                booked, court_number, slot_open, fail_reason = await try_book_court(
                    page, court_name, package_id, book_at_enc, target_date,
                    player_email, label,
                )

                if booked:
                    booked_court        = court_name
                    booked_court_number = court_number
                    booked_start_label  = start_label
                    booked_end_label    = end_label
                    booked_hour_str     = hour_str
                    break

                if slot_open:
                    window_open_this_round = True
                    failed_attempts.append(f"{court_name} {start_label}")
                    if fail_reason == "taken":
                        log(f"  [{label}] {court_name} {start_label}: already taken — trying next option.")
                    elif fail_reason == "payment_required":
                        manual_url = (
                            f"{BASE_URL}/org/4866/package/{package_id}"
                            f"?d={target_date}&v=7d&p=availability&book_at={book_at_enc}"
                        )
                        payment_attempts.append((court_name, start_label, manual_url))
                        log(f"  [{label}] {court_name} {start_label}: open but requires a real "
                            f"manual card payment — skipping (not booked automatically).")
                    else:
                        blocked_attempts.append((court_name, start_label, fail_reason))
                        log(f"  [{label}] {court_name} {start_label}: blocked by an error "
                            f"({fail_reason}) — trying next option.")
                else:
                    log(f"  [{label}] {court_name} {start_label}: no Réserver button — "
                        f"not offered at this time, trying next option.")
                await clear_cart(page, label)

            if booked_court:
                break

            if window_open_this_round:
                log(f"[{label}] Booking window open — every option in the priority list "
                    f"was checked this round.")
                break

            # Nothing anywhere responded this round — today's window likely
            # isn't open yet at all. Wait and try the whole list again.
            elapsed   = (datetime.now() - start_time).total_seconds()
            remaining = retry_total_secs - elapsed
            if remaining <= 0:
                log(f"[{label}] Retry window exhausted ({retry_total_secs}s) — "
                    f"no option in the priority list ever showed a Réserver button.")
                break
            wait = min(RETRY_INTERVAL_SECS, remaining)
            log(f"  [{label}] Booking window not open for any option — retrying in {wait:.0f}s "
                f"({remaining:.0f}s remaining).")
            await asyncio.sleep(wait)

        if booked_court:
            court_label = (
                f"{booked_court} Court {booked_court_number}"
                if booked_court_number else booked_court
            )
            log(f"[{label}] BOOKING COMPLETE — Court: {court_label} on {target_date} at {booked_start_label}")
            confirmation_body = (
                f"Court:   {court_label}\n"
                f"Date:    {target_date}\n"
                f"Time:    {booked_start_label} – {booked_end_label}\n"
                f"Players: {account['display_name']} + {player_name}\n"
                f"Source:  {config_source}"
            )
            success_recipients = [notify_email] if is_owner else [notify_email, GMAIL_ADDRESS]
            send_notification(
                subject=f"Tennis Booking ✅ {court_label}",
                body=confirmation_body,
                to_email=success_recipients,
            )
            if also_notify_player:
                send_notification(
                    subject=f"Tennis Booking ✅ {court_label}",
                    body=confirmation_body,
                    to_email=player_email,
                )
            log_booking_history(
                target_date, booked_court, booked_court_number,
                f"{booked_start_label} – {booked_end_label}", "success",
                f"Tried first: {', '.join(failed_attempts)}" if failed_attempts else "",
                account_label=label,
            )
            # Only create a calendar event when Sean is actually part of the
            # booking (i.e. it's his own account) — no event at all otherwise.
            if is_owner:
                calendar_ok = create_calendar_event(
                    target_date, booked_court, booked_court_number,
                    booked_hour_str, player_name,
                    owner_name=account["display_name"],
                )
                if not calendar_ok:
                    send_notification(
                        subject=f"Tennis Booking ⚠️ Calendar event failed ({target_date})",
                        body=(
                            f"The booking itself succeeded ({court_label} on {target_date} at "
                            f"{booked_start_label}), but the calendar event could not be created. "
                            f"Check booking.log for the underlying error — this usually means "
                            f"token.json's OAuth grant is missing the calendar.events scope "
                            f"(re-run setup_calendar_auth.py to fix)."
                        ),
                        to_email=failure_recipients,
                    )
        else:
            if not failed_attempts:
                # Nothing in the entire priority list ever showed a Réserver
                # button — the sentinel timed out AND the full fallback sweep
                # of every other court/time in the list came up empty too.
                tried_all = ", ".join(
                    f"{c} {TIME_SLOTS[h][0]}" for c, _, h in priority_list
                )
                reason = (
                    f"The booking window did not open within the retry window "
                    f"({retry_total_secs}s, {retry_total_secs // RETRY_INTERVAL_SECS} attempts), "
                    f"and no Réserver button appeared for any option on {target_date}. "
                    f"Tried: {tried_all}."
                )
                log(f"[{label}] BOOKING FAILED — booking window never opened. {reason}")
                send_notification(
                    subject=f"Tennis Booking ❌ Window never opened ({target_date})",
                    body=(
                        f"The booking window did not open in time on {target_date}.\n\n"
                        f"Retried {sentinel_name} {sentinel_label} every {RETRY_INTERVAL_SECS}s "
                        f"for {retry_total_secs}s starting at 9:30 PM, then checked every other "
                        f"option in the priority list — no Réserver button ever appeared for "
                        f"any of them: {tried_all}.\n\n"
                        f"You may need to book manually."
                    ),
                    to_email=failure_recipients,
                )
                log_booking_history(
                    target_date, None, None, None, "fail", reason,
                    account_label=label,
                )
            else:
                # Window opened but nothing got booked. Distinguish *why*:
                # genuine contention ("taken") vs. a config/site bug
                # (blocked_attempts) vs. a real-money payment the bot won't
                # submit unattended (payment_attempts) — collapsing these
                # into one generic "all slots taken" message is exactly what
                # buried the Jess-email-typo bug behind a false "unavailable"
                # read, so each gets its own callout here.
                tried = ", ".join(failed_attempts)

                if blocked_attempts:
                    detail = "; ".join(f"{c} {t}: {r}" for c, t, r in blocked_attempts)
                    log(f"[{label}] BOOKING FAILED — blocked by an error, not just unavailability: {detail}")
                    subject = f"Tennis Booking ⚠️ Blocked by an error ({target_date})"
                    body = (
                        f"The booking window opened on {target_date}, but at least one option "
                        f"failed for a reason that is NOT simple unavailability — this likely "
                        f"needs a config or site fix, not just a retry:\n\n"
                        f"{chr(10).join(f'  {c} {t}: {r}' for c, t, r in blocked_attempts)}\n\n"
                        f"Tried (in order): {tried}\n\n"
                        + (
                            "Also open (but requiring a manual card payment the bot won't "
                            "submit): " + "; ".join(f"{c} {t} — {u}" for c, t, u in payment_attempts) + "\n\n"
                            if payment_attempts else ""
                        )
                        + "You may need to book manually."
                    )
                    csv_note = f"Window opened, blocked by error. {detail}. Tried: {tried}"
                elif payment_attempts:
                    detail = "; ".join(f"{c} {t} — {u}" for c, t, u in payment_attempts)
                    log(f"[{label}] BOOKING FAILED — only a paid slot was open (requires manual payment): {detail}")
                    subject = f"Tennis Booking 💳 Manual payment needed ({target_date})"
                    body = (
                        f"The booking window opened on {target_date}, but the only open slot(s) "
                        f"required a real credit-card payment, which the bot never submits "
                        f"automatically:\n\n{detail}\n\n"
                        f"Tried (in order): {tried}\n\n"
                        f"Book manually at the link(s) above if you still want it."
                    )
                    csv_note = f"Window opened, only paid slot(s) open. {detail}. Tried: {tried}"
                else:
                    log(f"[{label}] BOOKING FAILED — window opened but all priority slots were taken.")
                    subject = f"Tennis Booking ❌ All slots taken ({target_date})"
                    body = (
                        f"The booking window opened but every priority slot was already "
                        f"taken on {target_date}.\n\n"
                        f"Tried (in order): {tried}\n\n"
                        f"You may need to book manually."
                    )
                    csv_note = f"Window opened, all slots taken. Tried: {tried}"

                send_notification(subject=subject, body=body, to_email=failure_recipients)
                log_booking_history(
                    target_date, None, None, None, "fail", csv_note,
                    account_label=label,
                )
    except Exception as e:
        # Catch-all for anything not already handled above (a site layout
        # change, a Playwright error, a network failure that survived
        # with_network_retry's backoff, etc.) — without this, an unexpected
        # exception here is only caught by main()'s generic
        # return_exceptions=True and logged as "UNHANDLED ERROR", with no
        # email and no booking_history row, so a real problem looks
        # identical to the script simply not having run.
        log(f"[{label}] UNEXPECTED ERROR: {e!r}\n{traceback.format_exc()}")
        send_notification(
            subject=f"Tennis Booking ⚠️ Unexpected error ({target_date})",
            body=(
                f"The booking attempt for {account['display_name']} crashed before finishing "
                f"— this is distinct from 'all slots taken' or 'session expired', it means "
                f"something broke mid-run (likely a network issue or a site change):\n\n"
                f"{e!r}\n\n"
                f"Check booking.log on the machine for the full traceback."
            ),
            to_email=failure_recipients,
        )
        log_booking_history(
            target_date, None, None, None, "fail",
            f"Unexpected error: {e!r}", account_label=label,
        )
    finally:
        await context.close()


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    log("=" * 60)
    log("Tennis booking script starting")
    log(f"Today: {date.today()}")

    for _name, _pkg, _hour in BOOKING_PRIORITY:
        if _hour not in TIME_SLOTS:
            log(f"CONFIG ERROR: hour {_hour!r} in BOOKING_PRIORITY is not in TIME_SLOTS — aborting.")
            send_notification(
                subject="Tennis Booking ⚠️ Config Error",
                body=f"Hour {_hour!r} in BOOKING_PRIORITY is not defined in TIME_SLOTS. Fix the configuration.",
            )
            return

    for account in ACCOUNTS:
        missing_keys = ACCOUNT_REQUIRED_KEYS - account.keys()
        if missing_keys:
            log(f"CONFIG ERROR: account {account.get('label', '?')!r} is missing keys {missing_keys} — aborting.")
            send_notification(
                subject="Tennis Booking ⚠️ Config Error",
                body=f"Account {account.get('label', '?')!r} in ACCOUNTS is missing keys {missing_keys}. Fix the configuration.",
            )
            return
        if not os.path.exists(account["auth_file"]):
            log(f"CONFIG ERROR: auth_file {account['auth_file']!r} for account {account['label']!r} does not exist — aborting.")
            send_notification(
                subject="Tennis Booking ⚠️ Config Error",
                body=(
                    f"auth_file {account['auth_file']!r} for account {account['label']!r} does not exist.\n\n"
                    f"Run: python save_auth.py {account['auth_file']}"
                ),
            )
            return
        for _name, _pkg, _hour in account.get("booking_priority") or []:
            if _hour not in TIME_SLOTS:
                log(f"CONFIG ERROR: hour {_hour!r} in account {account['label']!r}'s booking_priority "
                    f"is not in TIME_SLOTS — aborting.")
                send_notification(
                    subject="Tennis Booking ⚠️ Config Error",
                    body=(
                        f"Hour {_hour!r} in account {account['label']!r}'s booking_priority is not "
                        f"defined in TIME_SLOTS. Fix the configuration."
                    ),
                )
                return
        for _weekday, _entry in (account.get("weekday_players") or {}).items():
            for _name, _pkg, _hour in _entry[3] or []:
                if _hour not in TIME_SLOTS:
                    log(f"CONFIG ERROR: hour {_hour!r} in account {account['label']!r}'s "
                        f"weekday_players[{_weekday}] priority_override is not in TIME_SLOTS — aborting.")
                    send_notification(
                        subject="Tennis Booking ⚠️ Config Error",
                        body=(
                            f"Hour {_hour!r} in account {account['label']!r}'s "
                            f"weekday_players[{_weekday}] priority_override is not defined in "
                            f"TIME_SLOTS. Fix the configuration."
                        ),
                    )
                    return

    target_dt   = date.today() + timedelta(days=DAYS_AHEAD)
    target_date = target_dt.strftime("%Y-%m-%d")

    if TEST_MODE and TEST_BOOK_AT:
        target_date = TEST_BOOK_AT[:10]
        log(f"[TEST MODE] book_at={TEST_BOOK_AT}  d={target_date}")
    else:
        log(f"Target date : {target_date}  (today + {DAYS_AHEAD} days)")
        # Note: whether a weekend target is skipped is now decided per-account
        # inside run_account (accounts without "weekday_players" default to
        # Mon-Fri only; accounts with it use exactly their configured weekdays).

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        results = await asyncio.gather(
            *(run_account(browser, account, target_date) for account in ACCOUNTS),
            return_exceptions=True,
        )
        for account, result in zip(ACCOUNTS, results):
            if isinstance(result, Exception):
                log(f"[{account['label']}] UNHANDLED ERROR: {result!r}")

        await browser.close()

    log("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())