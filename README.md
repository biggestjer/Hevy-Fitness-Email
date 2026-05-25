# Hevy Daily Coaching Email

A Python script that pulls workout data from the Hevy API, analyzes it with Claude (Anthropic), and sends a detailed daily coaching report via Gmail SMTP — but only on days after you actually trained.

## What It Does

1. Fetches the last 30 days of workouts from Hevy (paginated)
2. Checks if you logged a workout yesterday — exits silently if not
3. Formats the raw workout JSON into a structured text summary including exercises, sets, weights, reps, RPE, and any in-app notes
4. Sends the summary to Claude Sonnet for deep analysis
5. Wraps the HTML response in an email template and delivers it via Gmail SMTP

The report is detailed and data-driven — it covers the most recent session's KPIs, volume trends across the last 3 sessions, a full progressive overload audit on every compound lift, critical imbalances, and an exact prescription for the next session.

## Project Structure

```
HEVY Project/
├── hevy_daily_email.py   # Main script
├── .env                  # Secret keys (never commit this)
├── .gitignore            # Excludes .env from git
└── README.md             # This file
```

## Environment Variables

Stored in `.env` using `python-dotenv`. Never hardcoded.

| Variable | Description |
|---|---|
| `HEVY_API_KEY` | Hevy API key — Settings → API in the Hevy app |
| `ANTHROPIC_API_KEY` | Anthropic API key — console.anthropic.com |
| `GMAIL_ADDRESS` | Gmail address used to send (and receive) the email |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not your real password) — myaccount.google.com/apppasswords |
| `RECIPIENT_EMAIL` | Where to send the report — same as `GMAIL_ADDRESS` for personal use |

## Dependencies

```bash
python3 -m pip install requests anthropic python-dotenv
```

> **Important:** Use `python3 -m pip` — not plain `pip`. On this machine, `pip` points to a different Python (Anaconda 3.8) than the one the script runs on (3.10). Using `python3 -m pip` ensures packages install into the correct environment.

- `requests` — Hevy API calls
- `anthropic` — Claude API
- `python-dotenv` — loads `.env` file

## Running the Script

```bash
python3 hevy_daily_email.py
```

Expected output when a workout was logged yesterday:
```
📥 Fetching workouts from Hevy...
   Found N workouts in the last 30 days.
📊 Summarizing workout data...
🤖 Analyzing with Claude...
📧 Sending email...
✅ Email sent to you@gmail.com
✅ Done!
```

Expected output on a rest day (no workout yesterday):
```
📥 Fetching workouts from Hevy...
   Found N workouts in the last 30 days.
⏭️  No workout logged yesterday — skipping email.
```

## Scheduling (Daily Cron)

Set the cron job without using an editor by running this once in your terminal:

```bash
(crontab -l 2>/dev/null; echo '0 8 * * * /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 "/Users/jerickaledezma/Documents/Projects/HEVY Project/hevy_daily_email.py"') | crontab -
```

Verify it saved:
```bash
crontab -l
```

Fires every day at 8am. On rest days the script exits immediately after the yesterday check — no Claude call, no email sent.

> **Note:** Do not use `crontab -e` from within Claude Code — it opens Vim in a non-interactive shell and will fail. Run the command above directly in Terminal instead.

## Key Configuration Constants

Both live at the top of `hevy_daily_email.py`:

- `LOOKBACK_DAYS = 30` — how far back to pull workouts from Hevy
- `HEVY_BASE_URL` — base URL for the Hevy API (`https://api.hevyapp.com/v1`)

## Claude Prompt Design

**Model:** `claude-sonnet-4-6`

**System prompt** instructs Claude to act as a brutally honest, data-driven strength coach. Key rules:
- Reference every exercise from the most recent session by name with exact weights and reps
- Compare each lift against previous sessions of the same muscle group using real numbers
- Compute KPIs: total volume per exercise, best set, volume trend, estimated 1RM trend
- Call out weaknesses and imbalances directly — no softening
- Output clean HTML with tables for KPI data

**User prompt** requests five sections:
1. **Last Session Deep-Dive** — every exercise with weight/reps and direct comparison to previous sessions of that muscle group
2. **KPI Dashboard** — table showing top set, total volume, and estimated 1RM across the last 3 sessions for that muscle group
3. **Progressive Overload Audit** — tracks every compound lift across the full 30-day log, flags stalls and regressions
4. **Critical Imbalances & Weaknesses** — top 2–3 imbalances with direct callouts
5. **Next Session Prescription** — exact exercise, weight, sets × reps — no vague advice

To adjust tone or focus, edit `SYSTEM_PROMPT` and `USER_PROMPT_TEMPLATE` in `hevy_daily_email.py`.

## Email Template

HTML wrapper lives in the `EMAIL_WRAPPER` constant. Styled for a clean inbox experience — max-width 680px, system fonts, minimal color. The subject line and date stamp are injected dynamically at send time.

## Common Issues

**Missing env variables** — the script calls `validate_config()` on startup and exits with a clear error listing which variables are missing.

**Wrong pip** — if you get `ModuleNotFoundError` after installing, you installed into the wrong Python. Always use `python3 -m pip install` instead of `pip install`.

**Hevy API pagination** — `fetch_recent_workouts()` loops through pages and stops as soon as it hits a workout older than `LOOKBACK_DAYS`. Workouts are returned newest-first by the API.

**Gmail authentication** — uses `smtplib.SMTP_SSL` on port 465. Requires a Gmail App Password (not your account password). App Passwords require 2FA to be enabled on the Google account first.

**Rest day check** — `worked_out_yesterday()` compares workout timestamps against yesterday's local date. If you train after midnight or your phone's timezone differs, a workout could be missed. Adjust the date logic in that function if needed.
