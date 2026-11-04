from uuid import uuid4


def draft(name: str = "Weekly report") -> dict:
    return {
        "name": name,
        "description": "Prepare a weekly pipeline report",
        "steps": [
            {
                "id": str(uuid4()),
                "name": "Prepare report",
                "goal": "Summarize the pipeline",
                "completion_criteria": "A summary covers changes and risks",
                "artifact_description": "A readable Markdown report",
            }
        ],
        "inputs": [
            {
                "key": "period",
                "label": "Reporting period",
                "description": "The period to summarize",
                "type": "text",
                "required": True,
            }
        ],
    }


def platform_admin_headers(context) -> dict[str, str]:
    """A Platform Admin session with no Organization membership."""
    from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

    organization, user, token = context.organization, context.user, context.access_token
    del context.organization
    try:
        user_id = uuid4()
        there_is_a_user(id=user_id, email=f"platform-{user_id}@example.com", is_platform_admin=True)(context)
        there_is_an_access_token_for_user(user_id)(context)
        return {"Authorization": f"Bearer {context.access_token}"}
    finally:
        context.organization, context.user, context.access_token = organization, user, token


def set_authoring(context, enabled: bool) -> None:
    from api.domains.workflows.platform_repository import PlatformWorkflowRepository

    context.injector.get(PlatformWorkflowRepository).set_authoring(
        enabled, context.user.id, context.user.full_name or context.user.email
    )


def authoring_is_enabled(context) -> None:
    from datetime import UTC, datetime

    from sqlmodel import Session

    from api.domains.workflows.platform_models import PlatformWorkflowSettings

    with Session(context.postgres_delegate.engine) as session:
        session.add(PlatformWorkflowSettings(authoring_enabled=True, updated_at=datetime.now(UTC)))
        session.commit()
