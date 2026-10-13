from fastapi import FastAPI
from fastapi_injector import attach_injector
from injector import Injector

from api.core.utils import create_injector
from api.domains.agent_memory.runtime_settings_routes import memory_runtime_settings_router


def create_memory_runtime_app(injector: Injector | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(memory_runtime_settings_router, prefix="/memory/runtime/v1")
    attach_injector(app, injector or create_injector())
    return app
