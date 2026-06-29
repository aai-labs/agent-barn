from fastapi import FastAPI
from fastapi_injector import attach_injector
from injector import Injector

import api.domains.agents.models
import api.domains.organizations.models
import api.domains.conversations.models
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
