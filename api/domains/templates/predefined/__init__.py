from dataclasses import dataclass

from api.domains.templates.defaults import (
    DEFAULT_AGENTS_MD,
    DEFAULT_BOOT_MD,
    DEFAULT_BOOTSTRAP_MD,
    DEFAULT_HEARTBEAT_MD,
)
from api.domains.templates.predefined import (
    code_reviewer,
    email_reminder,
    general_purpose,
    scrum_master,
)


@dataclass(frozen=True)
class PredefinedTemplate:
    slug: str
    name: str
    description: str
    soul_md: str
    identity_md: str
    user_md: str
    tools_md: str
    agents_md: str
    boot_md: str
    bootstrap_md: str
    heartbeat_md: str


PREDEFINED_TEMPLATES: tuple[PredefinedTemplate, ...] = (
    PredefinedTemplate(
        slug="general-purpose",
        name="General Purpose",
        description="A flexible, general-purpose agent ready to handle a broad range of tasks.",
        soul_md=general_purpose.SOUL_MD,
        identity_md=general_purpose.IDENTITY_MD,
        user_md=general_purpose.USER_MD,
        tools_md=general_purpose.TOOLS_MD,
        agents_md=DEFAULT_AGENTS_MD,
        boot_md=DEFAULT_BOOT_MD,
        bootstrap_md=DEFAULT_BOOTSTRAP_MD,
        heartbeat_md=DEFAULT_HEARTBEAT_MD,
    ),
    PredefinedTemplate(
        slug="scrum-master",
        name="Scrum Master",
        description="Runs your sprint ceremonies, tracks blockers, and keeps the team on cadence.",
        soul_md=scrum_master.SOUL_MD,
        identity_md=scrum_master.IDENTITY_MD,
        user_md=scrum_master.USER_MD,
        tools_md=scrum_master.TOOLS_MD,
        agents_md=scrum_master.AGENTS_MD,
        boot_md=scrum_master.BOOT_MD,
        bootstrap_md=DEFAULT_BOOTSTRAP_MD,
        heartbeat_md=scrum_master.HEARTBEAT_MD,
    ),
    PredefinedTemplate(
        slug="code-reviewer",
        name="PR Reviewer",
        description="Reviews pull requests for correctness, clarity, and style.",
        soul_md=code_reviewer.SOUL_MD,
        identity_md=code_reviewer.IDENTITY_MD,
        user_md=code_reviewer.USER_MD,
        tools_md=code_reviewer.TOOLS_MD,
        agents_md=code_reviewer.AGENTS_MD,
        boot_md=code_reviewer.BOOT_MD,
        bootstrap_md=DEFAULT_BOOTSTRAP_MD,
        heartbeat_md=code_reviewer.HEARTBEAT_MD,
    ),
    PredefinedTemplate(
        slug="email-reminder",
        name="Email Reminder",
        description="Monitors a mailbox, flags action-required emails, and posts P1/P2 priority pings to Slack.",
        soul_md=email_reminder.SOUL_MD,
        identity_md=email_reminder.IDENTITY_MD,
        user_md=email_reminder.USER_MD,
        tools_md=email_reminder.TOOLS_MD,
        agents_md=email_reminder.AGENTS_MD,
        boot_md=email_reminder.BOOT_MD,
        bootstrap_md=DEFAULT_BOOTSTRAP_MD,
        heartbeat_md=email_reminder.HEARTBEAT_MD,
    ),
)
