from fastapi import FastAPI
from fastapi_injector import attach_injector
from injector import Injector

from api.core.utils import create_injector
from api.domains.agent_memory.gateway_routes import memory_gateway_router
from api.domains.agent_memory.runtime_settings_routes import memory_runtime_settings_router
from api.domains.agent_memory.view_routes import memory_view_router


def create_memory_app(injector: Injector | None = None) -> FastAPI:
    injector = injector or create_injector()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    subapi = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    subapi.include_router(memory_gateway_router)
    app.mount("/memory/v1", subapi)
    # A separate application so Agent credentials never reach it and the Agent allowlist
    # never learns to list.
    viewer = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    viewer.include_router(memory_view_router)
    app.mount("/memory/view/v1", viewer)

    runtime = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    runtime.include_router(memory_runtime_settings_router)
    app.mount("/memory/runtime/v1", runtime)
    attach_injector(runtime, injector)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    attach_injector(app, injector)
    attach_injector(subapi, injector)
    attach_injector(viewer, injector)
    return app
