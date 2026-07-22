from fastapi import FastAPI
from fastapi_injector import attach_injector
from injector import Injector

import api.domains.agents.models  # noqa: F401 — register SQLModel tables for FK resolution
import api.domains.organizations.models  # noqa: F401
import api.domains.conversations.models  # noqa: F401
from api.core.utils import create_injector
from api.domains.ingest.routes import ingest_router


def create_ingest_app(injector: Injector | None = None):
    if injector is None:
        injector = create_injector()

    app = FastAPI()
    subapi = FastAPI()

    subapi.include_router(ingest_router)

    app.mount("/ingest/v1", subapi)

    attach_injector(app, injector)
    attach_injector(subapi, injector)

    return app
