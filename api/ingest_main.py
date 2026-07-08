from fastapi import FastAPI

from api.ingest_app import create_ingest_app

app: FastAPI = create_ingest_app()
