"""Machine-only SSH signing listener. No product or execution endpoints."""

import asyncio
import base64
import hashlib
import logging
import resource
from collections import Counter
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from injector import Injector
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from prometheus_client import Counter as MetricCounter

from api.core.config import Config
from api.core.utils import create_injector
from api.domains.ssh.protocol import EXTENSION, FAILURE, IDENTITIES, SIGN, validate_request
from api.domains.ssh.repository import SshRepository, token_digest
from api.domains.ssh.signer import OpenSshSigner

logger = logging.getLogger(__name__)
SUBPROTOCOL = "agentbarn.ssh-agent.v1"


def create_ssh_app(injector: Injector | None = None) -> FastAPI:
    injector = injector or create_injector()
    config = injector.get(Config)
    repository = injector.get(SshRepository)
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
        digest = token_digest(value)
        try:
            state, keys = await asyncio.to_thread(repository.authorize, digest)
        except HTTPException:
            await websocket.close(code=1008)
            return
        except Exception:
            await websocket.close(code=1011)
            return
        if total >= config.ssh_max_connections or connections[state.agent_id] >= config.ssh_max_agent_connections:
            await websocket.close(code=1013)
            return
        total += 1
        connections[state.agent_id] += 1
        active.inc()
        signer = OpenSshSigner(keys, config.agent_token_encryption_key, config.ssh_socket_directory)
        snapshot = [(key.id, key.revision) for key in keys]
        host_fingerprint = None
        try:
            await websocket.accept(subprotocol=SUBPROTOCOL)
            await asyncio.to_thread(signer.__enter__)
            while True:
                data = await asyncio.wait_for(websocket.receive_bytes(), config.ssh_idle_timeout_seconds)
                current, current_keys = await asyncio.to_thread(repository.authorize, digest)
                if (
                    current.generation != state.generation
                    or [(key.id, key.revision) for key in current_keys] != snapshot
                ):
                    await websocket.close(code=1008)
                    return
                try:
                    operation, blob = validate_request(data)
                except ValueError:
                    await websocket.send_bytes(FAILURE)
                    continue
                request_id = uuid4()
                key = signer.key_for_blob(blob) if operation == SIGN and blob else None
                if operation == SIGN:
                    await asyncio.to_thread(
                        repository.record_signing, state, key, "authorized", request_id, host_fingerprint
                    )
                response = await asyncio.to_thread(signer.exchange, data)
                if operation == EXTENSION and response == b"\x06" and blob:
                    host_fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
                if operation == SIGN:
                    outcome = "issued" if response[0] == 14 else "refused"
                    await asyncio.to_thread(
                        repository.record_signing, state, key, outcome, request_id, host_fingerprint
                    )
                    outcomes.labels(outcome=outcome).inc()
                if operation not in (IDENTITIES, SIGN, EXTENSION):
                    response = FAILURE
                await websocket.send_bytes(response)
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
            await asyncio.to_thread(signer.close)
            total -= 1
            active.dec()
            connections[state.agent_id] -= 1
            if not connections[state.agent_id]:
                del connections[state.agent_id]

    return app
