from fastapi import FastAPI
from fastapi_injector import attach_injector
from injector import Injector

from api.core.utils import create_injector
from api.domains.agent_memory.gateway_routes import memory_gateway_router


def create_memory_app(injector: Injector | None = None) -> FastAPI:
    injector = injector or create_injector()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    subapi = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    subapi.include_router(memory_gateway_router)
    app.mount("/memory/v1", subapi)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    attach_injector(app, injector)
    attach_injector(subapi, injector)
    return app
