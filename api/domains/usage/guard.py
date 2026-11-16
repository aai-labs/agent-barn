"""The question every service asks before new or more use: may this Organization do this?

Services name what the user is doing (`UsageAction`) and pass what the answer depends on.
They don't know what decides it: the implementation bound to `UsageGuard` does. Today that
is the Organization's Tier (`api.domains.tiers.usage_policy`). A refusal is an
`HTTPException` the implementation builds, so the response is the same wherever it is asked.

The guard runs after authorization and only gates new or more use: reading, editing,
disabling and deleting what an Organization already has never ask it.
"""

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from api.domains.usage.models import UsageSummary


class UsageAction(str, enum.Enum):
    """What the user is doing, named by the action rather than by what limits it."""

    HIRE_AGENT = "hire_agent"
    # Pinning an Agent to another Template, for which `UsageSubject.template` is given.
    REPIN_AGENT = "repin_agent"
    # Anything beyond the Template as published: skills, overrides, a selected Template.
    CUSTOMIZE_AGENT = "customize_agent"
    ADD_INTEGRATION = "add_integration"
    # Connecting a channel, and talking through one that needs no connection (Web Chat):
    # `UsageSubject.platform_key` names the Platform.
    CONNECT_CHANNEL = "connect_channel"
    USE_CHANNEL = "use_channel"
    CREATE_TEMPLATE = "create_template"
    CREATE_SKILL = "create_skill"
    CREATE_PLAYBOOK = "create_playbook"
    CREATE_WORKFLOW = "create_workflow"
    RUN_WORKFLOW = "run_workflow"
    ENABLE_WEBHOOK = "enable_webhook"
    ENABLE_MEMORY = "enable_memory"
    GRANT_MEMORY_ACCESS = "grant_memory_access"
    INVITE_MEMBER = "invite_member"
    BUY_CREDIT = "buy_credit"


@dataclass(frozen=True)
class TemplateChoice:
    """The Template an Agent is hired from or pinned to."""

    key: str
    # A Platform Template rather than one of the Organization's own.
    from_platform: bool
    agent_type: str


@dataclass(frozen=True)
class UsageSubject:
    """What an action's answer depends on, when it depends on more than the Organization."""

    platform_key: str | None = None
    template: TemplateChoice | None = None


class UsageGuard(ABC):
    @abstractmethod
    def allows(self, organization_id: UUID, action: UsageAction, subject: UsageSubject | None = None) -> bool:
        """Whether the action is allowed, for hiding or filtering what would be refused."""

    @abstractmethod
    def summary(self, organization_id: UUID, *, coverage: bool = False) -> UsageSummary:
        """The Organization's plan for its reads. `coverage` also works out whether it runs
        more than its plan covers, which costs a count of what it has."""

    @abstractmethod
    def check(self, organization_id: UUID, action: UsageAction, subject: UsageSubject | None = None) -> None:
        """Raise the refusal when the action isn't allowed."""
