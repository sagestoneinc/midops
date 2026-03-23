# MID Ops Report Bot — Setup & Deployment Guide

## Overview
Telegram bot that generates Nutra (Mint) and xShield MID performance reports with PNG screenshots, identical to the reports built in Claude. Supports on-demand commands and scheduled auto-runs.

## Features
- `/nutra 3pm-4pm` — Run Nutra MID report for today
- `/xshield 3pm-4pm` — Run xShield MID report for today
- `/both 3pm-4pm` — Run both reports
- `/both 3pm-4pm 2026-03-22` — Specify a date
- `/routing` — View current pool routing config
- `/set_visa TY_529=25,TY_530=50,...` — Update Visa pool weights
- `/set_mc TY_522_V2=20,...` — Update MC pool weights
- `/changes visa TY_523 switched off` — Set recent changes note
- `/clear_changes` — Clear all change notes
- Auto-scheduled reports (configurable in `config.py`)

## Prerequisites
1. **Python 3.10+**
2. **Telegram Bot Token** — Get from [@BotFather](https://t.me/BotFather)
3. **Google Cloud BigQuery** — Service account with BigQuery read access
4. **Playwright** — For HTML→PNG screenshot generation

## Quick Setup

### 1. Clone / copy files to your server
```
telegram-bot/
├── bot.py              # Main bot entry point
├── config.py           # Configuration (fill in credentials)
├── queries.py          # BigQuery data layer
├── report_builder.py   # Report formatting + HTML generation
├── routing_state.py    # Pool routing state manager
├── screenshot.py       # HTML → PNG via Playwright
├── requirements.txt    # Python dependencies
└── routing_state.json  # Auto-generated state file (persists routing)
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure
Edit `config.py`:
```python
TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."  # From BotFather
TELEGRAM_CHAT_ID = "-1001234567890"        # Your group chat ID
GCP_CREDENTIALS_PATH = "/path/to/key.json" # BigQuery service account
BQ_PROJECT = "your-project-id"
BQ_DATASET = "your-dataset"
```

### 4. Get your Telegram Chat ID
1. Add the bot to your group chat
2. Send a message in the group
3. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find the `chat.id` in the response (negative number for groups)

### 5. Run
```bash
python bot.py
```

### 6. (Optional) Run as a service
Create `/etc/systemd/system/midops-bot.service`:
```ini
[Unit]
Description=MID Ops Report Bot
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/telegram-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable midops-bot
sudo systemctl start midops-bot
sudo systemctl status midops-bot
```

## Scheduled Reports

Edit `config.py` to add auto-run schedules:
```python
SCHEDULED_REPORTS = [
    {"time": "10:05", "window_start": "09:00", "window_end": "10:00", "reports": ["nutra", "xshield"]},
    {"time": "14:05", "window_start": "13:00", "window_end": "14:00", "reports": ["nutra", "xshield"]},
    {"time": "18:05", "window_start": "17:00", "window_end": "18:00", "reports": ["nutra", "xshield"]},
    {"time": "22:05", "window_start": "21:00", "window_end": "22:00", "reports": ["nutra", "xshield"]},
]
```

Times are in EDT. The bot will automatically send PNG screenshots to the configured chat at each scheduled time.

## Routing Management

The bot persists routing state in `routing_state.json`. You can update it via Telegram commands:

```
# View current routing
/routing

# Update Visa pool (must sum to 100%)
/set_visa TY_529=20,TY_530=20,TY_531=40,TY_534=20

# Update MC pool
/set_mc TY_522_V2=20,TY_529_v2=20,TY_533_v2=20,TY_534_v2=40

# Set change notes (shows in report under each table)
/changes visa TY_523 switched off, TY_531 weight increased to 40%
/changes mc TY_532_v2 switched off, TY_534_v2 weight increased to 40%

# Clear all change notes
/clear_changes
```

## Report Output
- **PNG screenshot** sent as photo to Telegram (tables + Active MIDs + Recent Changes + footnotes only — no analysis)
- **Text summary** sent as message (includes analysis paragraph)

## Current Routing State (as of last session)

**Visa Pool #154:**
- TY_529 — 20%
- TY_530 — 20%
- TY_531 — 40%
- TY_534 — 20%

**MC Pool #155:**
- TY_522_V2 — 20%
- TY_529_v2 — 20%
- TY_533_v2 — 20%
- TY_534_v2 — 40%

**xShield Pool #4:**
- TY_6_Xshield (single MID)
