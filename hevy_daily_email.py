#!/usr/bin/env python3
"""
Hevy Workout Analyzer — Daily Email Script
==========================================
Pulls your recent Hevy workouts, analyzes them with Claude
(progressive overload + relative strength ratios), and emails
you a personalized coaching report via Gmail SMTP.

Setup:
  pip install requests anthropic

Environment variables (set these before running):
  HEVY_API_KEY       — Your Hevy API key (Settings → API in the app)
  ANTHROPIC_API_KEY  — Your Anthropic API key (console.anthropic.com)
  GMAIL_ADDRESS      — Your Gmail address (sender)
  GMAIL_APP_PASSWORD — Gmail App Password (NOT your regular password)
                       Generate at: myaccount.google.com/apppasswords
  RECIPIENT_EMAIL    — Where to send the report (can be same as GMAIL_ADDRESS)

Scheduling (run once daily):
  Mac/Linux cron — run `crontab -e` and add:
    0 8 * * * /usr/bin/python3 /path/to/hevy_daily_email.py
  Windows Task Scheduler — create a daily trigger pointing to this script.
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ────────────────────────────────────────────────────────────

HEVY_API_KEY = os.environ.get("HEVY_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", GMAIL_ADDRESS)

HEVY_BASE_URL = "https://api.hevyapp.com/v1"

# How many days back to look for workouts
LOOKBACK_DAYS = 30


# ── Hevy API helpers ──────────────────────────────────────────────────────────


def hevy_get(endpoint: str, params: dict = None) -> dict:
    """Make an authenticated GET request to the Hevy API."""
    headers = {
        "api-key": HEVY_API_KEY,
        "Accept": "application/json",
    }
    url = f"{HEVY_BASE_URL}{endpoint}"
    resp = requests.get(url, headers=headers, params=params or {}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_recent_workouts(days: int = LOOKBACK_DAYS) -> list[dict]:
    """Fetch all workouts from the past `days` days, handling pagination."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    workouts = []
    page = 1
    page_size = 10

    while True:
        data = hevy_get("/workouts", params={"page": page, "pageSize": page_size})
        batch = data.get("workouts", [])
        if not batch:
            break

        for w in batch:
            # Hevy timestamps are ISO-8601 strings
            start_str = w.get("start_time") or w.get("created_at", "")
            try:
                ts = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                ts = datetime.now(timezone.utc)

            if ts < cutoff:
                # Workouts are newest-first; stop once we go past the window
                return workouts

            workouts.append(w)

        # If this page had fewer results than page_size, we've hit the end
        if len(batch) < page_size:
            break
        page += 1

    return workouts


def summarize_workouts(workouts: list[dict]) -> str:
    """Convert raw Hevy workout JSON into a concise text summary for Claude."""
    if not workouts:
        return "No workouts found in the lookback period."

    lines = []
    for w in workouts:
        date_str = (w.get("start_time") or w.get("created_at", "Unknown date"))[:10]
        title = w.get("title", "Untitled workout")
        notes = w.get("description", "").strip()

        lines.append(f"\n### {title} — {date_str}")
        if notes:
            lines.append(f"Notes: {notes}")

        for ex in w.get("exercises", []):
            ex_title = ex.get(
                "title", ex.get("exercise_template_id", "Unknown exercise")
            )
            lines.append(f"\n  Exercise: {ex_title}")
            for s in ex.get("sets", []):
                weight_kg = s.get("weight_kg")
                reps = s.get("reps")
                rpe = s.get("rpe")
                set_type = s.get("set_type", "normal")
                set_note = s.get("notes", "").strip()

                parts = []
                if weight_kg is not None:
                    parts.append(f"{weight_kg} kg")
                if reps is not None:
                    parts.append(f"{reps} reps")
                if rpe is not None:
                    parts.append(f"RPE {rpe}")
                if set_type != "normal":
                    parts.append(f"[{set_type}]")

                set_str = "    - " + ", ".join(parts) if parts else "    - (no data)"
                if set_note:
                    set_str += f"  ← {set_note}"
                lines.append(set_str)

    return "\n".join(lines)


# ── Claude analysis ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a brutally honest, data-driven strength and conditioning coach.
You have access to a lifter's full recent workout log. Your job is to write a detailed,
critical coaching report — not a motivational summary. You must:

- Reference every exercise from the MOST RECENT session by name with exact weights and reps
- Compare each lift directly against previous sessions of the same muscle group to identify
  progression, stagnation, or regression — use real numbers (e.g. "bench went from 80kg×8 to 82.5kg×7 — volume dropped")
- Compute and display KPIs for the most recent session's target muscle group:
    • Total volume (sets × reps × weight) per exercise and overall
    • Best set (highest weight × reps)
    • Volume trend vs. the last 2–3 sessions of that same muscle group
    • Estimated 1RM trend on the primary lift
- Call out weaknesses, imbalances, and bad patterns directly — do not soften criticism
- Give a specific, numbered prescription for the next session (exact exercise, weight, sets × reps)
- Format your entire response as clean, well-structured HTML for email rendering.
  Use tables for KPI data. Use <h2> section headers. Do not use markdown."""

USER_PROMPT_TEMPLATE = """Here are my workouts from the past {days} days (newest first):

{workout_summary}

Write me a full coaching report email with the following sections:

---

## 1. Last Session Deep-Dive
Identify the most recent workout and its target muscle group(s). For every exercise in that session:
- List: exercise name | weight | sets × reps | total volume
- Compare to the last 1–3 times I trained that same muscle group. Did weight go up? Did volume drop?
  Be exact — "last chest session you hit 80kg×3×8 = 1,920kg volume; this session 82.5kg×3×6 = 1,485kg — that's a 22% volume drop despite the weight increase."

## 2. KPI Dashboard — Most Recent Session's Muscle Group
Display a table with these metrics across the last 3 sessions for that muscle group:
| Date | Exercise | Top Set | Total Volume | Est. 1RM |
Show the trend clearly. Is it going up, flat, or declining?

## 3. Progressive Overload Audit — All Main Lifts
For each primary compound lift in the log (squat, deadlift, bench, row, OHP, etc.):
- Show the weight/rep progression across all sessions in the log
- Call out any lift that has stalled (same weight 2+ sessions) or regressed
- Flag if I'm sacrificing reps for weight without justification

## 4. Critical Imbalances & Weaknesses
Based on the full log, identify the top 2–3 imbalances or weaknesses. Be direct:
- Push/pull ratio, quad/posterior chain ratio, dominant vs weak muscle groups
- Any exercises I'm avoiding or underloading relative to my other lifts

## 5. Next Session Prescription
Give me an exact plan for my next session. Specific exercise, specific weight target, sets × reps.
Do not be vague. Example: "Bench Press: 85kg × 4 × 6. If all reps clean, go to 87.5kg next session."

---

Do not pad the email with encouragement. Be direct. Use my actual numbers throughout."""


def analyze_with_claude(workout_summary: str) -> str:
    """Send the workout summary to Claude and get back an HTML analysis."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    days=LOOKBACK_DAYS,
                    workout_summary=workout_summary,
                ),
            }
        ],
    )
    return message.content[0].text


# ── Email sending ─────────────────────────────────────────────────────────────

EMAIL_WRAPPER = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          max-width: 680px; margin: 0 auto; padding: 24px; color: #1a1a1a; }}
  h1   {{ color: #e85d04; border-bottom: 2px solid #e85d04; padding-bottom: 8px; }}
  h2   {{ color: #2d6a4f; margin-top: 28px; }}
  h3   {{ color: #374151; }}
  ul, ol {{ line-height: 1.8; }}
  .badge {{ display: inline-block; background: #fef3c7; color: #92400e;
            border-radius: 4px; padding: 2px 8px; font-size: 12px; font-weight: 600; }}
  .footer {{ margin-top: 40px; font-size: 12px; color: #9ca3af;
             border-top: 1px solid #e5e7eb; padding-top: 16px; }}
</style>
</head>
<body>
  <h1>Your Daily Coaching Report</h1>
  <p style="color:#6b7280">{date}</p>
  {body}
  <div class="footer">
    Generated by your Hevy Workout Analyzer · Data from last {days} days
  </div>
</body>
</html>"""


def send_email(html_body: str):
    """Send the coaching report via Gmail SMTP."""
    today = datetime.now().strftime("%A, %B %-d %Y")
    full_html = EMAIL_WRAPPER.format(
        date=today,
        body=html_body,
        days=LOOKBACK_DAYS,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Hevy Coaching Report — {today}"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL

    # Plain text fallback
    plain = "Your daily coaching report is ready. Please view in an HTML-capable email client."
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(full_html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())

    print(f"✅ Email sent to {RECIPIENT_EMAIL}")


# ── Main ──────────────────────────────────────────────────────────────────────


def validate_config():
    missing = []
    for var in (
        "HEVY_API_KEY",
        "ANTHROPIC_API_KEY",
        "GMAIL_ADDRESS",
        "GMAIL_APP_PASSWORD",
        "RECIPIENT_EMAIL",
    ):
        if not os.environ.get(var):
            missing.append(var)
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        print("   See the setup instructions at the top of this file.")
        sys.exit(1)


def worked_out_yesterday(workouts: list[dict]) -> bool:
    """Return True if any workout started yesterday (local date)."""
    yesterday = (datetime.now() - timedelta(days=1)).date()
    for w in workouts:
        start_str = w.get("start_time") or w.get("created_at", "")
        try:
            ts = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            if ts.astimezone().date() == yesterday:
                return True
        except (ValueError, AttributeError):
            pass
    return False


def main():
    validate_config()

    print("📥 Fetching workouts from Hevy...")
    workouts = fetch_recent_workouts(days=LOOKBACK_DAYS)
    print(f"   Found {len(workouts)} workouts in the last {LOOKBACK_DAYS} days.")

    if not worked_out_yesterday(workouts):
        print("⏭️  No workout logged yesterday — skipping email.")
        sys.exit(0)

    print("📊 Summarizing workout data...")
    summary = summarize_workouts(workouts)

    print("🤖 Analyzing with Claude...")
    analysis_html = analyze_with_claude(summary)

    print("📧 Sending email...")
    send_email(analysis_html)

    print("✅ Done!")


if __name__ == "__main__":
    main()
