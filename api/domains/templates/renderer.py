import re
from dataclasses import dataclass
from datetime import UTC, datetime

from api.domains.agents.models import AgentTemplateOverrideVersion
from api.domains.templates.models import AgentTemplate, PlatformTemplate
from api.domains.templates.slug import slugify

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclass(frozen=True)
class RenderedTemplate:
    soul_md: str
    identity_md: str
    user_md: str
    tools_md: str
    agents_md: str
    boot_md: str
    bootstrap_md: str
    heartbeat_md: str


def _fill(text: str, variables: dict[str, str]) -> str:
    # Unknown/broken placeholders pass through unchanged.
    return _PLACEHOLDER.sub(lambda m: variables.get(m.group(1), m.group(0)), text)


def render_template(
    template: AgentTemplate | PlatformTemplate | AgentTemplateOverrideVersion,
    agent_name: str,
) -> RenderedTemplate:
    variables = {
        "agent_display_name": agent_name,
        "agent_name": slugify(agent_name) or "agent",
        # The Slack app display name is not persisted; the hire wizard keeps it
        # in sync with the agent name.
        "slack_app_display_name": agent_name,
        "deploy_date": datetime.now(UTC).date().isoformat(),
    }
    tools_md = _fill(template.tools_md, variables)
    return RenderedTemplate(
        soul_md=_fill(template.soul_md, variables),
        identity_md=_fill(template.identity_md, variables),
        user_md=_fill(template.user_md, variables),
        tools_md=tools_md,
        agents_md=_fill(template.agents_md, variables),
        boot_md=_fill(template.boot_md, variables),
        bootstrap_md=_fill(template.bootstrap_md, variables),
        heartbeat_md=_fill(template.heartbeat_md, variables),
    )
