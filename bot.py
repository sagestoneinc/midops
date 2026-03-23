#!/usr/bin/env python3
# ============================================================
# MID Ops Report Bot — Main Telegram Bot
# ============================================================
# Commands:
#   /nutra <start_time>-<end_time> [date]    — Run Nutra MID report
#   /xshield <start_time>-<end_time> [date]  — Run xShield MID report
#   /both <start_time>-<end_time> [date]     — Run both reports
#   /routing                                  — Show current routing config
#   /set_visa <mid1>=<weight>,<mid2>=<weight> — Update Visa routing
#   /set_mc <mid1>=<weight>,<mid2>=<weight>   — Update MC routing
#   /changes <visa|mc|xshield> <description>  — Set recent changes text
#   /clear_changes                            — Clear all recent changes
#   /help                                     — Show help
#
# Schedule: Configured in config.py SCHEDULED_REPORTS

import logging
import os
import re
import tempfile
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters
)

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SCHEDULED_REPORTS
from queries import (
    parse_time_window, check_data_availability, get_utc_offset,
    query_mint_mid_performance, query_mint_amex, query_mint_declines,
    query_xshield_performance, query_xshield_declines
)
from report_builder import build_nutra_report, build_xshield_report
from screenshot import generate_screenshot
from routing_state import (
    load_state, save_state, update_visa_routing, update_mc_routing,
    update_xshield_changes, clear_recent_changes
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ============================================================
# TIME PARSING HELPERS
# ============================================================

def parse_time_arg(text: str):
    """
    Parse time argument like '3pm-4pm', '3:00pm-4:30pm', '15:00-16:00'
    Returns (start_time_24h, end_time_24h) as 'HH:MM' strings.
    """
    text = text.strip().lower().replace(" ", "")

    # Split on dash
    parts = text.split("-")
    if len(parts) != 2:
        return None, None

    def parse_single(t):
        t = t.strip()
        # Handle am/pm
        is_pm = "pm" in t
        is_am = "am" in t
        t = t.replace("pm", "").replace("am", "").strip()

        if ":" in t:
            hour, minute = t.split(":")
            hour = int(hour)
            minute = int(minute)
        else:
            hour = int(t)
            minute = 0

        if is_pm and hour != 12:
            hour += 12
        if is_am and hour == 12:
            hour = 0

        return f"{hour:02d}:{minute:02d}"

    try:
        start = parse_single(parts[0])
        end = parse_single(parts[1])
        return start, end
    except (ValueError, IndexError):
        return None, None


def parse_date_arg(text: str, default_date: str = None):
    """Parse date argument or return today's date."""
    if not text:
        return default_date or datetime.now().strftime("%Y-%m-%d")

    text = text.strip().lower()
    if text == "today":
        return datetime.now().strftime("%Y-%m-%d")
    if text == "yesterday":
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Try various date formats
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%m/%d", "%m-%d"]:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.year < 2000:
                dt = dt.replace(year=datetime.now().year)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ============================================================
# REPORT GENERATION
# ============================================================

async def run_nutra_report(date_str: str, start_time: str, end_time: str):
    """Generate Nutra report and return (text, png_path)."""
    utc_start, utc_end = parse_time_window(date_str, start_time, end_time)

    # Check data availability
    avail = check_data_availability("mint_transactions_data", utc_start, utc_end)
    partial_note = ""
    if not avail["available"]:
        return "⚠️ No data available for this time window yet.", None

    # Query data
    perf = query_mint_mid_performance(utc_start, utc_end)
    amex = query_mint_amex(utc_start, utc_end)
    declines = query_mint_declines(utc_start, utc_end)

    # Format labels
    offset = get_utc_offset(date_str)
    tz_label = "EDT" if offset == -4 else "EST"
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    window_label = f"{dt.strftime('%B %d')}, {start_time} – {end_time} {tz_label}"
    utc_label = f"UTC: {utc_start.split(' ')[1][:5]}–{utc_end.split(' ')[1][:5]}"

    # Build report
    tg_text, html = build_nutra_report(perf, amex, declines, window_label, utc_label)

    # Generate screenshot
    png_path = tempfile.mktemp(suffix="_nutra.png")
    generate_screenshot(html, png_path, width=780)

    return tg_text, png_path


async def run_xshield_report(date_str: str, start_time: str, end_time: str):
    """Generate xShield report and return (text, png_path)."""
    # Today's window
    utc_start_today, utc_end_today = parse_time_window(date_str, start_time, end_time)

    # Yesterday's window
    yesterday = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    utc_start_yesterday, utc_end_yesterday = parse_time_window(yesterday, start_time, end_time)

    # Check data
    avail = check_data_availability("xshield_transactions_data", utc_start_today, utc_end_today)
    if not avail["available"]:
        return "⚠️ No xShield data available for this time window yet.", None

    # Query data
    perf = query_xshield_performance(utc_start_today, utc_end_today,
                                      utc_start_yesterday, utc_end_yesterday)
    declines = query_xshield_declines(utc_start_today, utc_end_today)

    # AMEX counts
    amex_today = {"sales": 0, "declines": 0}
    amex_yesterday = {"sales": 0, "declines": 0}
    for row in perf:
        if row.get("card_cc_type") == "american_express":
            if row["day_label"] == "Today":
                amex_today = {"sales": row["sales"], "declines": row["declines"]}
            elif row["day_label"] == "Yesterday":
                amex_yesterday = {"sales": row["sales"], "declines": row["declines"]}

    # Format labels
    offset = get_utc_offset(date_str)
    tz_label = "EDT" if offset == -4 else "EST"
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    yd = datetime.strptime(yesterday, "%Y-%m-%d")
    window_label = f"{dt.strftime('%B %d')}, {start_time} – {end_time} {tz_label}"
    utc_label = f"UTC: {utc_start_today.split(' ')[1][:5]}–{utc_end_today.split(' ')[1][:5]}"
    today_date = dt.strftime("Mar %d")
    yesterday_date = yd.strftime("Mar %d")

    # Build report
    tg_text, html = build_xshield_report(
        perf, declines, amex_today, amex_yesterday,
        window_label, utc_label, today_date, yesterday_date
    )

    # Generate screenshot
    png_path = tempfile.mktemp(suffix="_xshield.png")
    generate_screenshot(html, png_path, width=900)

    return tg_text, png_path


# ============================================================
# TELEGRAM COMMAND HANDLERS
# ============================================================

async def cmd_nutra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /nutra command."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /nutra <start>-<end> [date]\n"
            "Example: /nutra 3pm-4pm\n"
            "Example: /nutra 15:00-16:00 2026-03-22"
        )
        return

    start_time, end_time = parse_time_arg(args[0])
    if not start_time:
        await update.message.reply_text("❌ Could not parse time. Use format like: 3pm-4pm or 15:00-16:00")
        return

    date_str = parse_date_arg(args[1] if len(args) > 1 else None)
    if not date_str:
        await update.message.reply_text("❌ Could not parse date.")
        return

    await update.message.reply_text(f"⏳ Pulling Nutra report for {start_time}–{end_time} on {date_str}...")

    try:
        text, png_path = await run_nutra_report(date_str, start_time, end_time)
        if png_path:
            await update.message.reply_photo(photo=open(png_path, "rb"))
            os.unlink(png_path)
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Nutra report error: {e}")
        await update.message.reply_text(f"❌ Error generating report: {str(e)}")


async def cmd_xshield(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /xshield command."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /xshield <start>-<end> [date]\n"
            "Example: /xshield 3pm-4pm\n"
            "Example: /xshield 15:00-16:00 2026-03-22"
        )
        return

    start_time, end_time = parse_time_arg(args[0])
    if not start_time:
        await update.message.reply_text("❌ Could not parse time. Use format like: 3pm-4pm or 15:00-16:00")
        return

    date_str = parse_date_arg(args[1] if len(args) > 1 else None)

    await update.message.reply_text(f"⏳ Pulling xShield report for {start_time}–{end_time} on {date_str}...")

    try:
        text, png_path = await run_xshield_report(date_str, start_time, end_time)
        if png_path:
            await update.message.reply_photo(photo=open(png_path, "rb"))
            os.unlink(png_path)
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"xShield report error: {e}")
        await update.message.reply_text(f"❌ Error generating report: {str(e)}")


async def cmd_both(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /both command — runs both Nutra and xShield."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /both <start>-<end> [date]\n"
            "Example: /both 3pm-4pm"
        )
        return

    start_time, end_time = parse_time_arg(args[0])
    if not start_time:
        await update.message.reply_text("❌ Could not parse time.")
        return

    date_str = parse_date_arg(args[1] if len(args) > 1 else None)
    await update.message.reply_text(f"⏳ Pulling both reports for {start_time}–{end_time} on {date_str}...")

    try:
        # Nutra
        nutra_text, nutra_png = await run_nutra_report(date_str, start_time, end_time)
        if nutra_png:
            await update.message.reply_photo(photo=open(nutra_png, "rb"), caption="📊 Nutra MID Report")
            os.unlink(nutra_png)

        # xShield
        xs_text, xs_png = await run_xshield_report(date_str, start_time, end_time)
        if xs_png:
            await update.message.reply_photo(photo=open(xs_png, "rb"), caption="📊 xShield MID Report")
            os.unlink(xs_png)

    except Exception as e:
        logger.error(f"Both reports error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_routing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /routing — show current routing config."""
    state = load_state()

    text = "🔧 *Current Routing Configuration*\n\n"
    text += "*Visa Pool #154:*\n"
    for mid, weight in state["visa"]["active_mids"].items():
        text += f"  {mid} — {weight}%\n"
    text += f"  Recent Changes: {state['visa']['recent_changes']}\n\n"

    text += "*MC Pool #155:*\n"
    for mid, weight in state["mc"]["active_mids"].items():
        text += f"  {mid} — {weight}%\n"
    text += f"  Recent Changes: {state['mc']['recent_changes']}\n\n"

    text += "*xShield Pool #4:*\n"
    text += f"  {state['xshield']['active_mid']} (single MID)\n"
    text += f"  Recent Changes: {state['xshield']['recent_changes']}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_set_visa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /set_visa — update Visa routing weights."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /set_visa TY_529=20,TY_530=20,TY_531=40,TY_534=20\n"
            "Followed by: /changes visa <description>"
        )
        return

    try:
        raw = " ".join(context.args)
        pairs = raw.split(",")
        active_mids = {}
        for pair in pairs:
            mid, weight = pair.strip().split("=")
            active_mids[mid.strip()] = int(weight.strip())

        total = sum(active_mids.values())
        if total != 100:
            await update.message.reply_text(f"⚠️ Weights sum to {total}%, must be 100%")
            return

        state = load_state()
        changes = f"Updated to: {', '.join(f'{m} {w}%' for m, w in active_mids.items())}"
        update_visa_routing(state, active_mids, changes)
        await update.message.reply_text(f"✅ Visa routing updated:\n{changes}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_set_mc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /set_mc — update MC routing weights."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /set_mc TY_522_V2=20,TY_529_v2=20,TY_533_v2=20,TY_534_v2=40\n"
            "Followed by: /changes mc <description>"
        )
        return

    try:
        raw = " ".join(context.args)
        pairs = raw.split(",")
        active_mids = {}
        for pair in pairs:
            mid, weight = pair.strip().split("=")
            active_mids[mid.strip()] = int(weight.strip())

        total = sum(active_mids.values())
        if total != 100:
            await update.message.reply_text(f"⚠️ Weights sum to {total}%, must be 100%")
            return

        state = load_state()
        changes = f"Updated to: {', '.join(f'{m} {w}%' for m, w in active_mids.items())}"
        update_mc_routing(state, active_mids, changes)
        await update.message.reply_text(f"✅ MC routing updated:\n{changes}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_changes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /changes — set recent changes text."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /changes <visa|mc|xshield> <description>\n"
            "Example: /changes visa TY_523 switched off, TY_531 weight increased to 40%"
        )
        return

    brand = context.args[0].lower()
    description = " ".join(context.args[1:])
    state = load_state()

    if brand == "visa":
        state["visa"]["recent_changes"] = description
    elif brand == "mc":
        state["mc"]["recent_changes"] = description
    elif brand == "xshield":
        state["xshield"]["recent_changes"] = description
    else:
        await update.message.reply_text("❌ Brand must be: visa, mc, or xshield")
        return

    save_state(state)
    await update.message.reply_text(f"✅ {brand.upper()} recent changes updated: {description}")


async def cmd_clear_changes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear_changes — reset all recent changes to 'None'."""
    state = load_state()
    clear_recent_changes(state)
    await update.message.reply_text("✅ All recent changes cleared.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    text = """🤖 *MID Ops Report Bot — Commands*

📊 *Reports:*
/nutra 3pm-4pm — Run Nutra report (today)
/xshield 3pm-4pm — Run xShield report (today)
/both 3pm-4pm — Run both reports
/both 3pm-4pm 2026-03-22 — Specify date

🔧 *Routing:*
/routing — Show current config
/set\\_visa TY\\_529=25,TY\\_530=25,... — Update Visa
/set\\_mc TY\\_522\\_V2=20,... — Update MC
/changes visa TY\\_523 switched off — Set change note
/clear\\_changes — Clear all change notes
"""
    await update.message.reply_text(text, parse_mode="Markdown")


# ============================================================
# SCHEDULED REPORTS
# ============================================================

async def scheduled_report_job(context: ContextTypes.DEFAULT_TYPE):
    """Run scheduled reports and send to configured chat."""
    job_data = context.job.data
    date_str = datetime.now().strftime("%Y-%m-%d")
    start_time = job_data["window_start"]
    end_time = job_data["window_end"]
    reports = job_data["reports"]

    chat_id = TELEGRAM_CHAT_ID

    try:
        if "nutra" in reports:
            text, png = await run_nutra_report(date_str, start_time, end_time)
            if png:
                await context.bot.send_photo(chat_id=chat_id, photo=open(png, "rb"),
                                              caption="📊 Scheduled Nutra Report")
                os.unlink(png)

        if "xshield" in reports:
            text, png = await run_xshield_report(date_str, start_time, end_time)
            if png:
                await context.bot.send_photo(chat_id=chat_id, photo=open(png, "rb"),
                                              caption="📊 Scheduled xShield Report")
                os.unlink(png)
    except Exception as e:
        logger.error(f"Scheduled report error: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Scheduled report failed: {str(e)}")


# ============================================================
# MAIN
# ============================================================

def main():
    """Start the bot."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("nutra", cmd_nutra))
    app.add_handler(CommandHandler("xshield", cmd_xshield))
    app.add_handler(CommandHandler("both", cmd_both))
    app.add_handler(CommandHandler("routing", cmd_routing))
    app.add_handler(CommandHandler("set_visa", cmd_set_visa))
    app.add_handler(CommandHandler("set_mc", cmd_set_mc))
    app.add_handler(CommandHandler("changes", cmd_changes))
    app.add_handler(CommandHandler("clear_changes", cmd_clear_changes))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))

    # Schedule reports
    if SCHEDULED_REPORTS:
        job_queue = app.job_queue
        for sched in SCHEDULED_REPORTS:
            hour, minute = map(int, sched["time"].split(":"))
            from datetime import time as dt_time
            job_queue.run_daily(
                scheduled_report_job,
                time=dt_time(hour=hour, minute=minute),
                data=sched,
                name=f"report_{sched['time']}"
            )
            logger.info(f"Scheduled report at {sched['time']} EDT")

    logger.info("🤖 MID Ops Report Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
