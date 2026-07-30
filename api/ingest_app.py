from fastapi import FastAPI, Response
from fastapi_injector import attach_injector
from injector import Injector
from prometheus_client import REGISTRY

import api.domains.agents.models  # noqa: F401 — register SQLModel tables for FK resolution
import api.domains.organizations.models  # noqa: F401
import api.domains.conversations.models  # noqa: F401
from api.core.metrics import CONTENT_TYPE_LATEST, render_metrics, setup_http_metrics
from api.core.utils import create_injector
from api.domains.ingest.routes import ingest_router


def create_ingest_app(injector: Injector | None = None):
    if injector is None:
        injector = create_injector()

    app = FastAPI()
    subapi = FastAPI()

    subapi.include_router(ingest_router)

    app.mount("/ingest/v1", subapi)

    http_registry = setup_http_metrics(subapi)

    @app.get("/metrics")
    async def metrics():
        # The tool-call counter lives in this process's default registry; the
        # probe gauges are refreshed and exposed by the main app only.
        return Response(
            content=render_metrics(REGISTRY, http_registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    attach_injector(app, injector)
    attach_injector(subapi, injector)

    return app
