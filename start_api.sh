#!/bin/bash
cd "$(dirname "$0")"
exec ./venv/bin/uvicorn swiss_crm_api:app --port 8000 --host 0.0.0.0
