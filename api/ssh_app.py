"""Machine-only SSH signing listener. No product or execution endpoints."""

import asyncio
import logging
import resource
from collections import Counter
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from injector import Injector
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from prometheus_client import Counter as MetricCounter

from api.core.config import Config
from api.core.utils import create_injector
from api.domains.ssh.signing_service import SshSigningService

logger = logging.getLogger(__name__)
SUBPROTOCOL = "agentbarn.ssh-agent.v1"


def create_ssh_app(injector: Injector | None = None) -> FastAPI:
    injector = injector or create_injector()
    config = injector.get(Config)
    signing = injector.get(SshSigningService)
    connections: Counter[UUID] = Counter()
    total = 0
    metrics_registry = CollectorRegistry()
    active = Gauge("agentbarn_ssh_connections", "Active signing connections on this replica", registry=metrics_registry)
    outcomes = MetricCounter(
        "agentbarn_ssh_signatures", "Durably recorded signing outcomes", ["outcome"], registry=metrics_registry
    )

    @asynccontextmanager
    async def lifespan(app):
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health", status_code=204)
    async def health() -> None:
        return None

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(metrics_registry), media_type="text/plain; version=0.0.4; charset=utf-8")

    @app.websocket("/ssh/v1/agent")
    async def agent(websocket: WebSocket) -> None:
        nonlocal total
        authorization = websocket.headers.get("authorization", "")
        scheme, _, value = authorization.partition(" ")
        if (
            not config.ssh_enabled
            or scheme.lower() != "bearer"
            or not value
            or SUBPROTOCOL not in websocket.scope.get("subprotocols", [])
        ):
            await websocket.close(code=1008)
            return
        try:
            session = await asyncio.to_thread(signing.session, value)
        except HTTPException:
            await websocket.close(code=1008)
            return
        except Exception:
            await websocket.close(code=1011)
            return
        if total >= config.ssh_max_connections or connections[session.agent_id] >= config.ssh_max_agent_connections:
            await websocket.close(code=1013)
            return
        total += 1
        connections[session.agent_id] += 1
        active.inc()
        try:
            await websocket.accept(subprotocol=SUBPROTOCOL)
            await asyncio.to_thread(session.__enter__)
            while True:
                data = await asyncio.wait_for(websocket.receive_bytes(), config.ssh_idle_timeout_seconds)
                result = await asyncio.to_thread(session.exchange, data)
                if result.outcome:
                    outcomes.labels(outcome=result.outcome).inc()
                await websocket.send_bytes(result.payload)
        except WebSocketDisconnect:
            pass
        except HTTPException, TimeoutError:
            await websocket.close(code=1008)
        except Exception as exc:
            # OpenSSH, decrypted payloads and bearer credentials must never enter exception logs.
            logger.warning("SSH signing connection failed (%s)", type(exc).__name__)
            try:
                await websocket.close(code=1011)
            except RuntimeError:
                pass
        finally:
            await asyncio.to_thread(session.close)
            total -= 1
            active.dec()
            connections[session.agent_id] -= 1
            if not connections[session.agent_id]:
                del connections[session.agent_id]

    return app
