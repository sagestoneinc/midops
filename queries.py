# ============================================================
# MID Ops Report Bot — BigQuery Data Layer
# ============================================================
# All SQL queries for Nutra (Mint) and xShield reports.

from google.cloud import bigquery
from datetime import datetime, timedelta
import os

from config import (
    GCP_CREDENTIALS_PATH, USE_DEFAULT_CREDENTIALS,
    BQ_PROJECT, BQ_DATASET
)


def get_bq_client():
    """Initialize BigQuery client."""
    if USE_DEFAULT_CREDENTIALS:
        return bigquery.Client(project=BQ_PROJECT)
    else:
        return bigquery.Client.from_service_account_json(
            GCP_CREDENTIALS_PATH, project=BQ_PROJECT
        )


def run_query(sql: str) -> list:
    """Execute a BigQuery SQL query and return results as list of dicts."""
    client = get_bq_client()
    query_job = client.query(sql)
    results = query_job.result()
    return [dict(row) for row in results]


def get_utc_offset(date_str: str) -> int:
    """
    Determine UTC offset based on EDT/EST rules.
    EDT (UTC-4): Second Sunday of March → First Sunday of November
    EST (UTC-5): Outside that range
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    year = dt.year

    # Second Sunday of March
    march_1 = datetime(year, 3, 1)
    days_to_sunday = (6 - march_1.weekday()) % 7
    edt_start = march_1 + timedelta(days=days_to_sunday + 7)

    # First Sunday of November
    nov_1 = datetime(year, 11, 1)
    days_to_sunday = (6 - nov_1.weekday()) % 7
    est_start = nov_1 + timedelta(days=days_to_sunday)

    if edt_start <= dt < est_start:
        return -4  # EDT
    return -5  # EST


def parse_time_window(date_str: str, start_time: str, end_time: str):
    """
    Convert local EDT/EST time window to UTC timestamps.
    Returns (utc_start, utc_end) as strings suitable for BigQuery.
    """
    offset = get_utc_offset(date_str)
    utc_offset_hours = abs(offset)

    # Parse start
    start_dt = datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M")
    utc_start = start_dt + timedelta(hours=utc_offset_hours)

    # Parse end
    end_dt = datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M")
    utc_end = end_dt + timedelta(hours=utc_offset_hours)

    return utc_start.strftime("%Y-%m-%d %H:%M:%S"), utc_end.strftime("%Y-%m-%d %H:%M:%S")


def check_data_availability(table: str, utc_start: str, utc_end: str) -> dict:
    """Check latest available data in the requested window."""
    sql = f"""
    SELECT MAX(CAST(created_at AS TIMESTAMP)) AS latest
    FROM `{BQ_DATASET}.{table}`
    WHERE CAST(created_at AS TIMESTAMP) >= TIMESTAMP('{utc_start}')
      AND CAST(created_at AS TIMESTAMP) < TIMESTAMP('{utc_end}')
    """
    results = run_query(sql)
    if results and results[0]["latest"]:
        return {"available": True, "latest": str(results[0]["latest"])}
    return {"available": False, "latest": None}


# ============================================================
# NUTRA (MINT) QUERIES
# ============================================================

def query_mint_mid_performance(utc_start: str, utc_end: str) -> list:
    """Get MID performance data for Mint/Nutra."""
    sql = f"""
    WITH base AS (
      SELECT
        t.mid_name, t.card_cc_type, t.state, t.response_message,
        ROW_NUMBER() OVER (PARTITION BY t.order_id ORDER BY CAST(t.created_at AS TIMESTAMP) ASC) AS rn
      FROM `{BQ_DATASET}.mint_transactions_data` t
      JOIN `{BQ_DATASET}.mint_orders_data` o ON t.order_id = o.id
      WHERE t.upsell = false AND t.rebill_transaction = false
        AND t.reproc_transaction = false AND t.txn_type = 0
        AND o.affiliate_name NOT IN ('WIMMM', 'Internal')
        AND t.mid_name LIKE 'TY_%'
        AND CAST(t.created_at AS TIMESTAMP) >= TIMESTAMP('{utc_start}')
        AND CAST(t.created_at AS TIMESTAMP) < TIMESTAMP('{utc_end}')
    )
    SELECT
      mid_name, card_cc_type,
      COUNTIF(state = 'completed') AS sales,
      COUNTIF(state = 'failed') AS declines,
      COUNTIF(state = 'failed' AND LOWER(response_message) NOT IN
        ('insufficient funds', 'invalid card number', 'not enough balance')) AS hard_declines
    FROM base WHERE rn = 1
    GROUP BY mid_name, card_cc_type
    ORDER BY mid_name, card_cc_type
    """
    return run_query(sql)


def query_mint_amex(utc_start: str, utc_end: str) -> dict:
    """Get AMEX totals for Mint/Nutra."""
    sql = f"""
    WITH base AS (
      SELECT t.state,
        ROW_NUMBER() OVER (PARTITION BY t.order_id ORDER BY CAST(t.created_at AS TIMESTAMP) ASC) AS rn
      FROM `{BQ_DATASET}.mint_transactions_data` t
      JOIN `{BQ_DATASET}.mint_orders_data` o ON t.order_id = o.id
      WHERE t.upsell = false AND t.rebill_transaction = false
        AND t.reproc_transaction = false AND t.txn_type = 0
        AND o.affiliate_name NOT IN ('WIMMM', 'Internal')
        AND t.mid_name LIKE 'TY_%'
        AND LOWER(t.card_cc_type) = 'american_express'
        AND CAST(t.created_at AS TIMESTAMP) >= TIMESTAMP('{utc_start}')
        AND CAST(t.created_at AS TIMESTAMP) < TIMESTAMP('{utc_end}')
    )
    SELECT COUNTIF(state='completed') AS sales, COUNTIF(state='failed') AS declines
    FROM base WHERE rn=1
    """
    results = run_query(sql)
    return results[0] if results else {"sales": 0, "declines": 0}


def query_mint_declines(utc_start: str, utc_end: str) -> list:
    """Get decline breakdown per MID per card brand for Mint."""
    sql = f"""
    WITH base AS (
      SELECT t.mid_name, t.card_cc_type, t.response_message,
        ROW_NUMBER() OVER (PARTITION BY t.order_id ORDER BY CAST(t.created_at AS TIMESTAMP) ASC) AS rn
      FROM `{BQ_DATASET}.mint_transactions_data` t
      JOIN `{BQ_DATASET}.mint_orders_data` o ON t.order_id = o.id
      WHERE t.upsell = false AND t.rebill_transaction = false
        AND t.reproc_transaction = false AND t.txn_type = 0
        AND o.affiliate_name NOT IN ('WIMMM', 'Internal')
        AND t.mid_name LIKE 'TY_%' AND t.state = 'failed'
        AND LOWER(t.card_cc_type) IN ('visa', 'master')
        AND CAST(t.created_at AS TIMESTAMP) >= TIMESTAMP('{utc_start}')
        AND CAST(t.created_at AS TIMESTAMP) < TIMESTAMP('{utc_end}')
    )
    SELECT mid_name, card_cc_type, response_message, COUNT(*) AS cnt
    FROM base WHERE rn=1
    GROUP BY mid_name, card_cc_type, response_message
    ORDER BY mid_name, card_cc_type, cnt DESC
    """
    return run_query(sql)


# ============================================================
# XSHIELD QUERIES
# ============================================================

def query_xshield_performance(utc_start_today: str, utc_end_today: str,
                                utc_start_yesterday: str, utc_end_yesterday: str) -> list:
    """Get xShield performance for today and yesterday."""
    sql = f"""
    WITH base AS (
      SELECT
        CASE
          WHEN CAST(t.created_at AS TIMESTAMP) >= TIMESTAMP('{utc_start_today}')
           AND CAST(t.created_at AS TIMESTAMP) < TIMESTAMP('{utc_end_today}') THEN 'Today'
          WHEN CAST(t.created_at AS TIMESTAMP) >= TIMESTAMP('{utc_start_yesterday}')
           AND CAST(t.created_at AS TIMESTAMP) < TIMESTAMP('{utc_end_yesterday}') THEN 'Yesterday'
        END AS day_label,
        t.card_cc_type, t.state, t.response_message,
        ROW_NUMBER() OVER (PARTITION BY t.order_id ORDER BY CAST(t.created_at AS TIMESTAMP) ASC) AS rn
      FROM `{BQ_DATASET}.xshield_transactions_data` t
      JOIN `{BQ_DATASET}.xshield_orders_data` o ON t.order_id = o.id
      WHERE t.upsell = false AND t.rebill_transaction = false
        AND t.reproc_transaction = false AND t.txn_type = 0
        AND o.affiliate_name NOT IN ('WIMMM', 'Internal')
        AND t.mid_name = 'TY_6_Xshield'
        AND (
          (CAST(t.created_at AS TIMESTAMP) >= TIMESTAMP('{utc_start_today}')
           AND CAST(t.created_at AS TIMESTAMP) < TIMESTAMP('{utc_end_today}'))
          OR
          (CAST(t.created_at AS TIMESTAMP) >= TIMESTAMP('{utc_start_yesterday}')
           AND CAST(t.created_at AS TIMESTAMP) < TIMESTAMP('{utc_end_yesterday}'))
        )
    )
    SELECT day_label, card_cc_type,
      COUNTIF(state = 'completed') AS sales,
      COUNTIF(state = 'failed') AS declines,
      COUNTIF(state = 'failed' AND LOWER(response_message) NOT IN
        ('insufficient funds', 'invalid card number', 'not enough balance')) AS hard_declines
    FROM base WHERE rn = 1
    GROUP BY day_label, card_cc_type
    ORDER BY day_label, card_cc_type
    """
    return run_query(sql)


def query_xshield_declines(utc_start: str, utc_end: str) -> list:
    """Get today's decline breakdown for xShield."""
    sql = f"""
    WITH base AS (
      SELECT t.card_cc_type, t.response_message,
        ROW_NUMBER() OVER (PARTITION BY t.order_id ORDER BY CAST(t.created_at AS TIMESTAMP) ASC) AS rn
      FROM `{BQ_DATASET}.xshield_transactions_data` t
      JOIN `{BQ_DATASET}.xshield_orders_data` o ON t.order_id = o.id
      WHERE t.upsell = false AND t.rebill_transaction = false
        AND t.reproc_transaction = false AND t.txn_type = 0
        AND o.affiliate_name NOT IN ('WIMMM', 'Internal')
        AND t.mid_name = 'TY_6_Xshield'
        AND t.state = 'failed'
        AND LOWER(t.card_cc_type) != 'american_express'
        AND CAST(t.created_at AS TIMESTAMP) >= TIMESTAMP('{utc_start}')
        AND CAST(t.created_at AS TIMESTAMP) < TIMESTAMP('{utc_end}')
    )
    SELECT card_cc_type, response_message, COUNT(*) AS cnt
    FROM base WHERE rn = 1
    GROUP BY card_cc_type, response_message
    ORDER BY card_cc_type, cnt DESC
    """
    return run_query(sql)
