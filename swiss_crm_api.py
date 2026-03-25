#!/usr/bin/env python3
# ============================================================
# SwissCRM BigQuery API — FastAPI server for ChatGPT Actions
# ============================================================
# Exposes 4 endpoints that mirror the SwissCRM MCP tools:
#   GET  /tables                   — list all tables in the dataset
#   GET  /tables/{table_id}/columns — schema for a specific table
#   GET  /columns                  — all column definitions
#   POST /query                    — execute a SELECT statement
#
# ChatGPT reads the OpenAPI spec at /openapi.json to build its Action.
#
# Run locally:
#   uvicorn swiss_crm_api:app --port 8000 --reload
#
# Expose publicly for ChatGPT (local dev):
#   ngrok http 8000
# ============================================================

import os
from dotenv import load_dotenv
from typing import Optional

from fastapi import FastAPI, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from google.cloud import bigquery
from pydantic import BaseModel

# Load .env file if present
load_dotenv()

# ── Configuration (set via environment variables or .env) ──────────────────
BQ_PROJECT = os.environ.get("BQ_PROJECT", "bigquery-470313")
BQ_DATASET = os.environ.get("BQ_DATASET", "")          # e.g. "swisscrm"
GCP_CREDENTIALS_PATH = os.environ.get(
    "GCP_CREDENTIALS_PATH",
    "/Users/jeselcura/Downloads/ai-bigquery-service-account.json"
)
API_KEY = os.environ.get("SWISS_CRM_API_KEY", "")       # Set a strong secret

# ── FastAPI app ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="SwissCRM BigQuery API",
    description=(
        "Query the SwissCRM BigQuery database. "
        "Supports listing tables, inspecting schemas, and running SELECT queries."
    ),
    version="1.0.0",
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# ── Auth ────────────────────────────────────────────────────────────────────

def require_api_key(key: Optional[str] = Security(api_key_header)):
    if API_KEY and key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return key


# ── BigQuery helpers ────────────────────────────────────────────────────────

def get_bq_client() -> bigquery.Client:
    if GCP_CREDENTIALS_PATH and os.path.exists(GCP_CREDENTIALS_PATH):
        return bigquery.Client.from_service_account_json(
            GCP_CREDENTIALS_PATH, project=BQ_PROJECT
        )
    return bigquery.Client(project=BQ_PROJECT)


def run_sql(sql: str) -> list[dict]:
    client = get_bq_client()
    job_config = bigquery.QueryJobConfig(
        default_dataset=f"{BQ_PROJECT}.{BQ_DATASET}" if BQ_DATASET else None
    )
    job = client.query(sql, job_config=job_config)
    rows = job.result()
    return [dict(row) for row in rows]


# ── Pydantic models ─────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    sql: str


class ColumnInfo(BaseModel):
    name: str
    type: str
    mode: str
    description: Optional[str] = None


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get(
    "/tables",
    summary="List all tables",
    description="Returns the list of all table IDs in the SwissCRM dataset.",
    tags=["Schema"],
)
def list_tables(_: str = Security(require_api_key)):
    client = get_bq_client()
    if not BQ_DATASET:
        raise HTTPException(status_code=500, detail="BQ_DATASET env var not set")
    dataset_ref = bigquery.DatasetReference(BQ_PROJECT, BQ_DATASET)
    tables = list(client.list_tables(dataset_ref))
    return {"tables": [t.table_id for t in tables]}


@app.get(
    "/tables/{table_id}/columns",
    summary="Get columns for a table",
    description="Returns column name, type, mode, and description for the given table.",
    tags=["Schema"],
)
def get_table_columns(table_id: str, _: str = Security(require_api_key)):
    client = get_bq_client()
    if not BQ_DATASET:
        raise HTTPException(status_code=500, detail="BQ_DATASET env var not set")
    try:
        table_ref = bigquery.TableReference(
            bigquery.DatasetReference(BQ_PROJECT, BQ_DATASET), table_id
        )
        table = client.get_table(table_ref)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Table not found: {e}")

    columns = [
        ColumnInfo(
            name=field.name,
            type=field.field_type,
            mode=field.mode,
            description=field.description or None,
        )
        for field in table.schema
    ]
    return {"table": table_id, "columns": [c.model_dump() for c in columns]}


@app.get(
    "/columns",
    summary="Get all column definitions",
    description="Returns column definitions for every table in the dataset.",
    tags=["Schema"],
)
def get_all_columns(_: str = Security(require_api_key)):
    client = get_bq_client()
    if not BQ_DATASET:
        raise HTTPException(status_code=500, detail="BQ_DATASET env var not set")
    dataset_ref = bigquery.DatasetReference(BQ_PROJECT, BQ_DATASET)
    all_tables = list(client.list_tables(dataset_ref))

    result = {}
    for t in all_tables:
        table_ref = bigquery.TableReference(dataset_ref, t.table_id)
        table = client.get_table(table_ref)
        result[t.table_id] = [
            {"name": f.name, "type": f.field_type, "mode": f.mode}
            for f in table.schema
        ]
    return {"tables": result}


@app.post(
    "/query",
    summary="Execute a SQL query",
    description=(
        "Runs a BigQuery SQL SELECT statement against the SwissCRM dataset "
        "and returns the results as a list of JSON objects. "
        "Only SELECT statements are permitted."
    ),
    tags=["Query"],
)
def execute_query(body: QueryRequest, _: str = Security(require_api_key)):
    sql = body.sql.strip()
    if not sql.upper().startswith("SELECT"):
        raise HTTPException(
            status_code=400,
            detail="Only SELECT statements are allowed."
        )
    try:
        rows = run_sql(sql)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"rows": rows, "count": len(rows)}


# ── Health check (no auth required) ────────────────────────────────────────

@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
