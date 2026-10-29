from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.environment_health.models import EnvironmentHealthRead
from api.domains.environment_health.service import EnvironmentHealthService

# Platform Oversight surface: no Active Organization is resolved. Read-only: there is no
# route here that deletes, restarts or changes anything in the cluster.
platform_environment_health_router = APIRouter(
    prefix="/platform/environment-health", tags=["platform-environment-health"]
)


@platform_environment_health_router.get("", response_model=EnvironmentHealthRead)
def get_environment_health(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[EnvironmentHealthService, Injected(EnvironmentHealthService)],
):
    return service.get_health()
