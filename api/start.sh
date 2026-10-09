#!/bin/sh
uvicorn api.ingest_main:app --host 0.0.0.0 --port 8001 &
if [ -n "$MEMORY_RUNTIME_SERVICE_KEY" ]; then
    uvicorn api.memory_runtime_main:app --host 0.0.0.0 --port 8004 --no-access-log &
fi
exec fastapi run api/main.py --port 8000
