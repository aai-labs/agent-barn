from dataclasses import dataclass

from api.domains.templates.defaults import (
    DEFAULT_AGENTS_MD,
    DEFAULT_BOOT_MD,
    DEFAULT_BOOTSTRAP_MD,
    DEFAULT_HEARTBEAT_MD,
)
from api.domains.templates.predefined import (
    code_reviewer,
    documentation_agent,
    email_reminder,
    general_purpose,
    jira_task_helper,
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
    required_skill_names: tuple[str, ...] = ()


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
        required_skill_names=("Jira", "Confluence"),
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
        # Code host is GitHub OR Bitbucket — an "either" the AND-only skill gate
        # can't express, so it's enforced at runtime by AGENTS.md Setup Step 1.
        # Configuring either host auto-mounts its aai-cli skill at start.
        required_skill_names=(),
    ),
    PredefinedTemplate(
        slug="jira-task-helper",
        name="Jira Task Helper",
        description="Turns a plain-language request — in any language — into a well-structured Jira task and files it for you.",
        soul_md=jira_task_helper.SOUL_MD,
        identity_md=jira_task_helper.IDENTITY_MD,
        user_md=jira_task_helper.USER_MD,
        tools_md=jira_task_helper.TOOLS_MD,
        agents_md=jira_task_helper.AGENTS_MD,
        boot_md=jira_task_helper.BOOT_MD,
        bootstrap_md=DEFAULT_BOOTSTRAP_MD,
        heartbeat_md=DEFAULT_HEARTBEAT_MD,
        required_skill_names=("Jira",),
    ),
    PredefinedTemplate(
        slug="documentation-agent",
        name="Documentation Agent",
        description="Documents merged pull requests (GitHub or Bitbucket) into Confluence, keeps a changelog, and posts a weekly digest of what shipped to Slack.",
        soul_md=documentation_agent.SOUL_MD,
        identity_md=documentation_agent.IDENTITY_MD,
        user_md=documentation_agent.USER_MD,
        tools_md=documentation_agent.TOOLS_MD,
        agents_md=documentation_agent.AGENTS_MD,
        boot_md=documentation_agent.BOOT_MD,
        bootstrap_md=DEFAULT_BOOTSTRAP_MD,
        heartbeat_md=documentation_agent.HEARTBEAT_MD,
        required_skill_names=("Jira", "Confluence"),
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
