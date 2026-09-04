import logging
import traceback
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi_injector import Injected, attach_injector
from injector import Injector
from prometheus_client import REGISTRY
from sqlmodel import Session, select

from api.core.config import get_config
from api.core.metrics import (
    CONTENT_TYPE_LATEST,
    PROBE_REGISTRY,
    refresh_agents_in_error,
    refresh_database_gauge,
    refresh_openrouter_credits,
    render_metrics,
    setup_http_metrics,
)
from api.core.utils import create_injector
from api.domains.agent_settings.routes import agent_settings_router
from api.domains.agents.routes import agents_router
from api.domains.agents.service import AgentService
from api.domains.auth.routes import auth_router
from api.domains.communications.metrics import refresh_communication_metrics
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.communications.routes import communications_router
from api.domains.conversations.routes import conversations_router
from api.domains.costs.routes import costs_router
from api.domains.events.routes import event_delivery_monitor_router
from api.domains.integrations.google_oauth.routes import integrations_router
from api.domains.organizations.routes import org_router, platform_org_router
from api.domains.platform_admin.routes import platform_stats_router
from api.domains.rbac.seeder import RbacSeeder
from api.domains.shared_credentials.routes import shared_credentials_router
from api.domains.skills.repository import SkillRepository
from api.domains.skills.routes import agent_skills_router, platform_skills_router, skills_router
from api.domains.skills.skill_seeder import seed_aai_cli_skills
from api.domains.templates.routes import platform_templates_router, templates_router
from api.domains.templates.service import TemplateService
from api.domains.tool_calls.routes import tool_calls_router
from api.domains.users.organization_users.routes import member_router, platform_member_router
from api.domains.users.routes import users_router
from api.domains.users.service import UserService
from api.domains.web_chat.routes import web_chat_router
from api.infrastructure.email.logging_utils import (
    log_email_delivery_disabled_warning,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    config = get_config()
    if not config.is_email_delivery_enabled:
        log_email_delivery_disabled_warning(logger)

    injector = create_injector()
    user_service = injector.get(UserService)

    try:
        injector.get(RbacSeeder).seed()
        user_service.ensure_default_platform_admin()

        seed_aai_cli_skills(injector.get(SkillRepository))
        injector.get(TemplateService).seed_predefined_templates()
    except Exception:
        logger.error("Error during startup bootstrap: %s", traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error while initializing startup data",
        )

    yield


def create_app(injector: Injector | None = None):
    if injector is None:
        injector = create_injector()

    app_v1 = FastAPI(lifespan=lifespan)
    subapi = FastAPI()

    @subapi.get("/health")
    async def health_v1(
        db: Annotated[PostgresRepositoryDelegate, Injected(PostgresRepositoryDelegate)],
    ):
        try:
            with Session(db.engine) as session:
                session.exec(select(1))
            return {"status": "ok", "db": "connected"}
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"status": "error", "db": "disconnected"},
            )

    app_v1.mount("/api/v1", subapi)

    subapi.include_router(agents_router)
    subapi.include_router(agent_settings_router)
    subapi.include_router(auth_router)
    subapi.include_router(conversations_router)
    subapi.include_router(communications_router)
    subapi.include_router(web_chat_router)
    subapi.include_router(costs_router)
    subapi.include_router(event_delivery_monitor_router)
    subapi.include_router(platform_stats_router)
    subapi.include_router(org_router)
    subapi.include_router(platform_org_router)
    subapi.include_router(member_router)
    subapi.include_router(platform_member_router)
    subapi.include_router(shared_credentials_router)
    subapi.include_router(skills_router)
    subapi.include_router(agent_skills_router)
    subapi.include_router(platform_skills_router)
    subapi.include_router(integrations_router)
    subapi.include_router(templates_router)
    subapi.include_router(platform_templates_router)
    subapi.include_router(tool_calls_router)
    subapi.include_router(users_router)

    http_registry = setup_http_metrics(subapi)

    @app_v1.get("/metrics")
    async def metrics(
        db: Annotated[PostgresRepositoryDelegate, Injected(PostgresRepositoryDelegate)],
        agent_service: Annotated[AgentService, Injected(AgentService)],
        communication_operations: Annotated[
            CommunicationOperationalRepository,
            Injected(CommunicationOperationalRepository),
        ],
    ):
        refresh_database_gauge(db.engine)
        refresh_agents_in_error(agent_service.count_agents_in_error)
        refresh_openrouter_credits()
        refresh_communication_metrics(communication_operations)
        return Response(
            content=render_metrics(REGISTRY, PROBE_REGISTRY, http_registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    attach_injector(app_v1, injector)
    attach_injector(subapi, injector)

    origins = [
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
    ]

    app_v1.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    return app_v1
