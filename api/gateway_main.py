from fastapi import FastAPI

from api.gateway_app import create_gateway_app

app: FastAPI = create_gateway_app()
