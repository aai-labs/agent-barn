#!/bin/sh
uvicorn api.ingest_main:app --host 0.0.0.0 --port 8001 &
exec fastapi run api/main.py --port 8000
