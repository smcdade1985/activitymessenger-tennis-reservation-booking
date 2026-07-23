# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A nightly Playwright bot that books tennis courts on Activity Messenger. It runs via Windows Task Scheduler at 9:30:30 PM Sun–Fri (Friday was added so Patrick's account can target a Saturday-morning slot) and targets a slot 8 days out. `book_tennis.py` is the only production script; everything else is a one-time setup helper or exploration artifact.

## Running the script

```bash
python book_tennis.py
```

No build step. Output goes to stdout and `booking.log`. Each outcome is appended to `booking_history.csv`.

## Testing a specific slot

Set `TEST_MODE = True` and `TEST_BOOK_AT` to the URL-encoded `book_at` value at the top of `book_tennis.py`, then run normally. To compute the encoded value:

```bash
python -c "from urllib.parse import quote; print(quote('YYYY-MM-DDTHH:MM:SS-0400', safe=''))"
```

`TEST_BOOK_AT[:10]` is used as `target_date`, so the full encoded datetime must be the first field. Reset both to `False`/`""` after testing.

## Key runtime dependencies

```bash
pip install playwright openpyxl google-auth google-auth-oauthlib google-api-python-client google-auth-httplib2 tzdata
playwright install chromium
```

`tzdata` is required on Windows for `ZoneInfo("America/Montreal")` to work. `google-auth-httplib2` is used to put a short timeout on the optional Google Sheet config read (see below).

## Credential files (all gitignored)

| File | How to regenerate |
|------|-------------------|
| `auth.json`, `auth_<label>.json` | `python save_auth.py [output_path]` — opens browser, log in within 3 min. Defaults to `auth.json` if no path given. |
| `email_config.py` | Create manually: `GMAIL_APP_PASSWORD = "..."` |
| `token.json` | `python setup_calendar_auth.py` — browser OAuth flow. Grants both `calendar.events` and `spreadsheets.readonly` scopes (the latter for the Sheet config below). Adding/removing a scope from `setup_calendar_auth.py`'s `SCOPES` invalidates the saved token — delete `token.json` and re-run interactively to re-consent. |
| `local_config.py` | Create manually. Holds `GMAIL_ADDRESS`, `SHEET_SPREADSHEET_ID`, `KNOWN_PLAYERS` (email → name), and `ACCOUNTS` (see `book_tennis.py`'s `ACCOUNTS`/`KNOWN_PLAYERS` comments for the expected shape of each) — real names/emails, kept out of the tracked source. |

Each account's `auth_*.json` expires periodically; the script detects this per-account, skips that account's booking, and emails an alert to that account's `notify_email`.

## Architecture of `book_tennis.py`

`main()` validates config, then launches one shared headless browser and runs `run_account()` concurrently (via `asyncio.gather`) for every entry in `ACCOUNTS`, each in its own browser context/session. One account's exception doesn't stop the others.

Each `run_account()` call runs one retry loop, one round at a time:

**Each round walks the entire priority list in order**, moving to the next court/time immediately the moment one comes back without a `Réserver` button — no single court ever monopolizes the retry budget. A missing `Réserver` only proves that specific slot isn't open right now (today's window may not have opened yet, or that court may just not carry that hour at all on this day of the week) — it does not mean no other option in the list is bookable. This matters most for accounts whose priority list mixes courts with genuinely different per-day offerings (e.g. Patrick's Saturday list tries 9 AM at all three courts, but JV/RP don't carry a 9 AM slot on Saturdays at all while DLV does — checking JV alone for the full retry window used to cause the whole run to give up without ever trying DLV).

**End of round:** if anything booked, done. If any option in the round came back open-but-taken, the window is confirmed open — the round finishes sweeping whatever's left in the list, then the whole attempt stops (no further rounds). Only when an entire round comes back completely empty (every option, no response at all) does the script sleep `RETRY_INTERVAL_SECS` and try the full list again, up to `RETRY_TOTAL_SECS` total.

**`try_book_court` return values:** `(booked: bool, court_number: str|None, slot_open: bool)`. `slot_open=False` means the `Réserver` button was absent for that specific court/time (either the day's window isn't open yet, or that slot just isn't offered); `slot_open=True` means the button was present but the slot was taken or an error occurred. `slot_open=False` always means "move on to the next option," never "abort the round."

**Confirmation detection:** After the checkout wizard, the script checks for `"réservation est confirmée"` in the page text before returning `booked=True`. This string comes from the live confirmation page — do not change it without verifying against the site.

Since accounts run concurrently, all `log()` lines, screenshot filenames, and `booking_history.csv` notes are prefixed with the account's `label` to keep them attributable.

## Configuration (top of `book_tennis.py`)

- `BOOKING_PRIORITY` — ordered list of `(court_name, package_id, hour_str)` tuples, shared by every account. Every `hour_str` must exist as a key in `TIME_SLOTS` or the script aborts at startup.
- `TIME_SLOTS` — maps `"HH:MM:SS"` to `("start label", "end label")` display strings. Covers every hourly slot the platform actually offers (07:00–21:00), not just the subset `BOOKING_PRIORITY` tries by default — this is what bounds valid `target_time` values from the Sheet config below.
- `DAYS_AHEAD` — days ahead to book (default 8).
- `ACCOUNTS` — one dict per login the script books for, all run in parallel each night:
  - `label` — short slug used in logs, screenshot filenames, and CSV notes.
  - `display_name` — name `check_session_valid` looks for on the logged-in homepage.
  - `auth_file` — that account's Playwright storage-state file.
  - `second_player_email` / `second_player_name` — that account's own playing partner, selected from its saved-contacts dropdown.
  - `notify_email` — where booking confirmations/alerts are emailed (sent from Sean's Gmail via `email_config.py`).
  - `is_owner` — `True` only for Sean's own account. Sean is never one of the two players in anyone else's booking, so **a calendar event is only ever created for `is_owner` accounts** — no event at all gets created for a booking Sean isn't part of. Every account's confirmation email always CC's Sean on success (in addition to always CC'ing him on failures).
  - `booking_priority` (optional) — overrides the shared `BOOKING_PRIORITY` for this account only (e.g. same courts, different hour). Acts as the account's default whenever a weekday in `weekday_players` doesn't specify its own `priority_override`. Every `hour_str` in it must also exist in `TIME_SLOTS`, checked at startup.
  - `weekday_players` (optional) — `{weekday_int: (email, name, also_email_player_on_success, priority_override)}`, `0`=Monday..`6`=Sunday, keyed on the *target* date's weekday. When set, the account only attempts a booking on the listed weekdays (every other target date is skipped, logged to `booking_history.csv` with status `skipped`, no alert sent) and uses that weekday's player instead of `second_player_email`/`second_player_name`. `also_email_player_on_success` CC's that player on the confirmation email. `priority_override` is a `(court_name, package_id, hour_str)` list used only for that weekday, or `None` to fall back to `booking_priority`/`BOOKING_PRIORITY`.
  - **Accounts without `weekday_players`** (e.g. Sean's) default to the original Mon-Fri-only behavior — weekend target dates are skipped automatically. This replaced a script-wide weekend abort that used to live in `main()`; the weekday gate is now per-account, inside `run_account`.
  - `sheet_tab` (optional) — name of that account's tab in the Google Sheet config (see below). Accounts without it never touch the Sheet and behave exactly as documented above.

**Adding a new account:** run `python save_auth.py auth_<label>.json` (log in as that person within the 3-minute window), then append an entry to `ACCOUNTS` with their details. The script validates at startup that every account has all required keys and that its `auth_file` exists.

## Optional Google Sheet config

Each account can optionally be controlled from a phone via a Google Sheet, without changing any hardcoded behavior. Purely additive: if the Sheet can't be read for **any** reason (network, auth, missing tab, malformed rows), that account books exactly as it would with no Sheet at all — this is enforced structurally (`load_sheet_config` returns `None` on any exception, and callers only ever apply overrides when it returns a dict).

- **Spreadsheet**: `SHEET_SPREADSHEET_ID` (top of `book_tennis.py`). Tabs are per-account, named to match each account's `sheet_tab` value (currently `Sean's Bookings` and `Pat's Bookings`).
- **Schema**: each tab is a key/value table in range `<tab>!A2:B`, with row keys `enabled`, `date_mode`, `target_date`, `target_time`, `player_2`.
  - `enabled` — must be exactly `TRUE` (case-insensitive) for the Sheet to take effect at all this run. Anything else, **including a blank/missing cell**, skips that account's booking entirely for the night (logged as `skipped`, not an error, and emailed so it's not silently missed) — this is a deliberate off-switch, not a fail-open default.
  - `date_mode` — `auto` (default) or `manual`. Only gates `target_date` (see below) — it has no effect on `target_time` or `player_2`, which apply the same way regardless of `date_mode`. `manual` requires `target_date` to exactly equal `today + DAYS_AHEAD`; this is a sanity check against fat-fingering, not a way to book a different day (the site only ever opens that one day's window nightly). If it matches, it also bypasses that account's weekday gate for this one run — the only way a weekend booking happens for an account with no matching `weekday_players` entry. In `auto` mode (the default), `target_date` is never read at all — it can be blank, stale, or anything else with zero effect.
  - `target_time` — optional, and **applied every run regardless of `date_mode`** — it is not scoped to `manual` mode or to whatever `target_date` says, and it does not expire or auto-clear once the date it was meant for has passed. Accepts `H:MM`, `HH:MM`, or `HH:MM:SS`; normalized and validated against `TIME_SLOTS` (07:00–21:00, every hour — verified against the live availability grid for all three courts). Substitutes this hour into every `(court, package_id, hour)` tuple of whichever priority list would otherwise apply, preserving court fallback order. Blank keeps the default. **A value left over from a one-off manual override will keep silently applying every subsequent night** until someone blanks the cell — this bit us on 2026-07-19, when a `target_time` set on 2026-07-16 for a one-time 2026-07-24 booking kept forcing 10 AM instead of the default 11 AM three nights later. Blank the cell as soon as the one-off override is no longer needed.
  - `player_2` — optional, same "applies every run regardless of `date_mode`, doesn't auto-clear" caveat as `target_time` above. Must be a **name** (not an email) from `KNOWN_PLAYERS`' values (see `local_config.py`, gitignored), matched case-insensitively via `NAME_TO_EMAIL`. Intended to be a Sheet dropdown (Data validation) listing exactly those names, so it can't be mistyped. Overrides the account's default/`weekday_players` player for this run. Blank keeps the default.
  - Any present-but-invalid value (bad/mismatched date, unrecognized time, unknown player) aborts the booking for that account (not just that field) and emails the raw Sheet contents plus which field failed.
- Success emails append `Source: sheet` or `Source: default` depending on whether an override was applied.
- Adding a new known player: add them to both `KNOWN_PLAYERS` (in `local_config.py`) and the Sheet's `player_2` dropdown list.

## Court package IDs

| Court | Package ID |
|-------|-----------|
| JV | 2592 |
| RP | 2590 |
| DLV | 2434 |

Booking URL pattern: `https://activitymessenger.com/org/4866/package/{package_id}?d={date}&v=7d&p=availability&book_at={encoded_datetime}`
