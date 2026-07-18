import logging
import traceback
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi_injector import attach_injector, Injected
from injector import Injector
from sqlmodel import Session, select

from api.core.config import get_config
from api.core.utils import create_injector
from api.domains.agents.routes import agents_router
from api.domains.agents.slack_routes import slack_router
from api.domains.agents.webhook_routes import webhook_router
from api.domains.auth.routes import auth_router
from api.domains.conversations.routes import conversations_router
from api.domains.costs.routes import costs_router
from api.domains.integrations.google_oauth.routes import integrations_router
from api.domains.organizations.routes import org_router
from api.domains.rbac.seeder import RbacSeeder
from api.domains.skills.routes import skills_router
from api.domains.skills.skill_seeder import seed_aai_cli_skills
from api.domains.templates.routes import templates_router
from api.domains.templates.service import TemplateService
from api.domains.tool_calls.routes import tool_calls_router
from api.domains.users.organization_users.routes import member_router
from api.domains.users.routes import users_router
from api.domains.users.service import UserService
from api.domains.organizations.service import OrganizationService
from api.domains.skills.repository import SkillRepository
from api.domains.auth.utils import set_default_org_id
from api.domains.rbac.catalog import OWNER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationUser
from api.domains.users.organization_users.repository import OrganizationUserRepository
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
        superuser = user_service.ensure_default_superuser()

        org_service = injector.get(OrganizationService)
        default_org = org_service.ensure_default_organization()
        set_default_org_id(default_org.id)

        seed_aai_cli_skills(injector.get(SkillRepository))

        template_service = injector.get(TemplateService)
        template_service.seed_predefined_templates(default_org.id)

        org_user_repo = injector.get(OrganizationUserRepository)
        if not org_user_repo.get_by_user_id_and_organization_id(
            superuser.id, default_org.id
        ):
            org_user_repo.save(
                OrganizationUser(
                    user_id=superuser.id,
                    organization_id=default_org.id,
                    role_id=OWNER_ROLE_ID,
                )
            )
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
    subapi.include_router(webhook_router)
    subapi.include_router(auth_router)
    subapi.include_router(conversations_router)
    subapi.include_router(costs_router)
    subapi.include_router(org_router)
    subapi.include_router(member_router)
    subapi.include_router(skills_router)
    subapi.include_router(integrations_router)
    subapi.include_router(templates_router)
    subapi.include_router(tool_calls_router)
    subapi.include_router(users_router)
    subapi.include_router(slack_router)

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
