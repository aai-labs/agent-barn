from fastapi import FastAPI

from api.memory_proxy_app import create_memory_proxy_app

app: FastAPI = create_memory_proxy_app()
