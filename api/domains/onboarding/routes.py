from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user, require_platform_admin
from api.domains.onboarding.models import OnboardingRead, TrialSettingsRead, TrialSettingsUpdate
from api.domains.onboarding.service import OnboardingService
from api.domains.onboarding.settings_service import TrialSettingsService

onboarding_router = APIRouter(prefix="/onboarding", tags=["onboarding"])
platform_trial_settings_router = APIRouter(prefix="/platform/settings/trial", tags=["platform-settings"])


@platform_trial_settings_router.get("", response_model=TrialSettingsRead)
def read_trial_settings(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TrialSettingsService, Injected(TrialSettingsService)],
):
    return service.read(context)


@platform_trial_settings_router.put("", response_model=TrialSettingsRead)
def update_trial_settings(
    data: TrialSettingsUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TrialSettingsService, Injected(TrialSettingsService)],
):
    return service.update(data, context)


@onboarding_router.get("", response_model=OnboardingRead)
def read_onboarding(
    context: Annotated[CurrentUserContext, Depends(get_current_user(require_organization=False))],
    service: Annotated[OnboardingService, Injected(OnboardingService)],
):
    return service.read(context)


@onboarding_router.post("/agent", response_model=OnboardingRead)
def set_up_onboarding_agent(
    context: Annotated[CurrentUserContext, Depends(get_current_user(require_organization=False))],
    service: Annotated[OnboardingService, Injected(OnboardingService)],
):
    """Create and start the trial's Agent and its Telegram Connection, doing only what is
    still missing. Safe to call again, e.g. to retry an Agent that failed to start."""
    return service.set_up_agent(context)


@onboarding_router.post("/complete", status_code=status.HTTP_204_NO_CONTENT)
def complete_onboarding(
    context: Annotated[CurrentUserContext, Depends(get_current_user(require_organization=False))],
    service: Annotated[OnboardingService, Injected(OnboardingService)],
):
    service.complete(context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
