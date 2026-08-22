from fastapi import FastAPI

from api.communications_app import create_communications_app

app: FastAPI = create_communications_app()
