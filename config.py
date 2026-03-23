# ============================================================
# MID Ops Report Bot — Configuration
# ============================================================
# Fill in your credentials before deploying.

# Telegram Bot Token (get from @BotFather)
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"

# Telegram Chat ID(s) where reports should be sent
# Can be a group chat ID (negative number) or user ID
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"

# Google Cloud BigQuery credentials
# Option 1: Path to service account JSON key file
GCP_CREDENTIALS_PATH = "path/to/your/service-account-key.json"

# Option 2: If running on GCP with default credentials, set this to True
USE_DEFAULT_CREDENTIALS = False

# BigQuery dataset
BQ_PROJECT = "your-gcp-project-id"
BQ_DATASET = "your-dataset-name"

# ============================================================
# Report Defaults
# ============================================================

# Timezone offset: UTC-4 for EDT, UTC-5 for EST
# The bot auto-detects based on date, but you can override here
TIMEZONE_OVERRIDE = None  # Set to -4 or -5 to force

# Performance thresholds
NUTRA_ADJ_AR_THRESHOLD = 60.0  # Bold if below this
XSHIELD_ADJ_AR_THRESHOLD = 50.0  # Bold if below this
THIN_VOLUME_THRESHOLD = 20  # Mark with * if below this

# ============================================================
# Schedule Configuration (optional)
# ============================================================
# Define auto-run schedules as list of dicts
# Each entry: {"time": "HH:MM", "timezone": "EDT", "reports": ["nutra", "xshield"]}
# The bot will run these reports automatically and send to TELEGRAM_CHAT_ID
SCHEDULED_REPORTS = [
    # Example:
    # {"time": "10:00", "window_start": "09:00", "window_end": "10:00", "reports": ["nutra", "xshield"]},
    # {"time": "14:00", "window_start": "13:00", "window_end": "14:00", "reports": ["nutra", "xshield"]},
    # {"time": "18:00", "window_start": "17:00", "window_end": "18:00", "reports": ["nutra", "xshield"]},
    # {"time": "22:00", "window_start": "21:00", "window_end": "22:00", "reports": ["nutra", "xshield"]},
]
