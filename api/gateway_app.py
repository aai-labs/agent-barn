from fastapi import FastAPI, Response
from fastapi_injector import attach_injector
from injector import Injector
from prometheus_client import REGISTRY

import api.domains.agents.models
import api.domains.credential_gateway.models
import api.domains.organizations.models  # noqa: F401
from api.core.metrics import CONTENT_TYPE_LATEST, render_metrics, setup_http_metrics
from api.core.utils import create_injector
from api.domains.credential_gateway.routes import gateway_router


def create_gateway_app(injector: Injector | None = None) -> FastAPI:
    """The credential gateway process.

    A separate deployment from the product API: it sits on the request path of every
    agent tool call, so its availability, scaling, and blast radius are deliberately
    independent of the API's. It ships in the same image, so the Integration Plugins it
    imports need no separate packaging.
    """
    if injector is None:
        injector = create_injector()

    app = FastAPI()
    subapi = FastAPI()
    subapi.include_router(gateway_router)
    app.mount("/gateway/v1", subapi)

    http_registry = setup_http_metrics(subapi)

    @app.get("/metrics")
    async def metrics():
        return Response(
            content=render_metrics(REGISTRY, http_registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    attach_injector(app, injector)
    attach_injector(subapi, injector)
    return app
