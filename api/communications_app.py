import asyncio
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi_injector import attach_injector
from injector import Injector
from prometheus_client import REGISTRY

from api.core.metrics import CONTENT_TYPE_LATEST, render_metrics, setup_http_metrics
from api.core.utils import create_injector
from api.domains.communications.gateway_routes import (
    driver_communications_router,
    provider_webhook_router,
    runtime_communications_router,
)
from api.domains.communications.metrics import refresh_communication_metrics
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.communications.processor import OutboundCommunicationProcessor
from api.domains.communications.supervisor import PlatformIngressSupervisor


def create_communications_app(injector: Injector | None = None) -> FastAPI:
    if injector is None:
        injector = create_injector()

    stop = threading.Event()

    def process_outbound() -> None:
        processor = injector.get(OutboundCommunicationProcessor)
        while not stop.is_set():
            if not processor.process_one():
                stop.wait(0.5)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        worker = threading.Thread(target=process_outbound, name="communications-outbound", daemon=True)
        worker.start()
        ingress_stop = asyncio.Event()
        ingress_task = asyncio.create_task(
            injector.get(PlatformIngressSupervisor).run(ingress_stop),
            name="communications-ingress-supervisor",
        )
        try:
            yield
        finally:
            ingress_stop.set()
            await ingress_task
            stop.set()
            worker.join(timeout=5)

    app = FastAPI(lifespan=lifespan)
    subapi = FastAPI()
    subapi.include_router(runtime_communications_router)
    subapi.include_router(driver_communications_router)
    subapi.include_router(provider_webhook_router)
    app.mount("/communications/v1", subapi)

    http_registry = setup_http_metrics(subapi)

    @app.get("/metrics")
    async def metrics():
        refresh_communication_metrics(injector.get(CommunicationOperationalRepository))
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
