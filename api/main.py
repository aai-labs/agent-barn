from fastapi import FastAPI

from api.api_app import create_app

app: FastAPI = create_app()
