"""Audit coverage registry.

Every API route must be classified here as either audited (mapped to the action it
records) or explicitly exempt (with a reason). ``test_audit_route_coverage`` walks the
app's routes and fails CI if any route is in neither map — so adding an endpoint forces a
deliberate decision about its audit story, which is how the ticket's "err toward capturing
more / the action set can grow" survives future development.

The map is keyed on the route handler's function ``__name__``. It is documentation, not
wiring: the actual ``record()`` calls live in the services/routes. Keeping them listed
here (rather than introspected) is intentional — it's a human-maintained checklist.

Placement: mutations record in services (post-commit); reads record in the route —
unless the service method already holds the agent (for the target label) and isn't
reused internally, in which case the read records in the service too.
"""

from api.domains.audit_logs.models import AuditAction

# Route function name -> the action(s) it records.
AUDITED_ROUTES: dict[str, AuditAction | tuple[AuditAction, ...]] = {
    # agents
    "create_agent": AuditAction.AGENT_CREATE,
    "update_agent": AuditAction.AGENT_UPDATE,
    "delete_agent": AuditAction.AGENT_DELETE,
    "start_agent": AuditAction.AGENT_START,
    "stop_agent": AuditAction.AGENT_STOP,
    "get_agent": AuditAction.AGENT_VIEW,
    "get_agent_logs": AuditAction.AGENT_LOGS_VIEW,
    "get_agent_log_history": AuditAction.AGENT_LOGS_VIEW,
    # slack
    "create_slack_app_route": AuditAction.INTEGRATION_SLACK_APP_CREATE,
    # auth
    "login_for_access_token": (AuditAction.AUTH_LOGIN, AuditAction.AUTH_LOGIN_FAILED),
    "logout": AuditAction.AUTH_LOGOUT,
    "change_current_user_password": AuditAction.AUTH_PASSWORD_CHANGE,
    "forgot_password": AuditAction.AUTH_PASSWORD_RESET_REQUEST,
    "reset_password": AuditAction.AUTH_PASSWORD_RESET,
    "set_password": AuditAction.AUTH_SET_PASSWORD,
    "save_slack_config_token": AuditAction.AUTH_SLACK_CONFIG_TOKEN_SAVE,
    "delete_slack_config_token": AuditAction.AUTH_SLACK_CONFIG_TOKEN_DELETE,
    # conversations
    "list_channels": AuditAction.AGENT_CONVERSATIONS_VIEW,
    "list_channel_messages": AuditAction.AGENT_CONVERSATIONS_VIEW,
    # costs
    "get_cost_summary": AuditAction.COST_VIEW,
    "get_agent_cost": AuditAction.COST_VIEW,
    # organizations
    "create_organization": AuditAction.ORG_CREATE,
    "update_organization": AuditAction.ORG_UPDATE,
    "delete_organization": AuditAction.ORG_DELETE,
    # skills
    "create_skill": AuditAction.SKILL_CREATE,
    "update_skill": AuditAction.SKILL_UPDATE,
    "delete_skill": AuditAction.SKILL_DELETE,
    # templates
    "create_template": AuditAction.TEMPLATE_CREATE,
    "update_template": AuditAction.TEMPLATE_UPDATE,
    # tool calls
    "list_tool_calls": AuditAction.AGENT_TOOL_CALLS_VIEW,
    # users (superuser admin)
    "create_user": AuditAction.USER_CREATE,
    "reset_user_password": AuditAction.USER_PASSWORD_RESET,
    "delete_user": AuditAction.USER_DELETE,
    # members
    "add_member": AuditAction.MEMBER_ADD,
    "change_member_role": AuditAction.MEMBER_ROLE_CHANGE,
    "remove_member": AuditAction.MEMBER_REMOVE,
    "transfer_ownership": AuditAction.MEMBER_OWNERSHIP_TRANSFER,
    "resend_invite": AuditAction.MEMBER_INVITE_RESEND,
    # audit log itself
    "list_audit_logs": AuditAction.AUDIT_LOG_VIEW,
    "export_audit_logs": AuditAction.AUDIT_LOG_EXPORT,
}

# Route function name -> why it is not audited.
AUDIT_EXEMPT_ROUTES: dict[str, str] = {
    # infra / health
    "health_v1": "infra health probe, not a user action",
    "get_agent_healthz": "UI polling; high-frequency status probe",
    # token/session mechanics, not user intent
    "refresh_access_token": "token refresh, not a distinct user action",
    "get_current_user_context": "reads own identity (/me); every page load",
    "signup": "disabled stub endpoint",
    # live endpoints with no frontend path — nothing reaches them from the app
    "pair_agent": "no frontend path (use-pair-agent hook is unused)",
    "update_current_user_profile": "no frontend path (account page has no name edit)",
    # read-only credential check, auto-fired on viewing the secrets tab (no user action)
    "validate_integration": "read-only re-check; auto-fires per secret on secrets-tab view",
    # pure list / lookup endpoints (the corresponding detail/mutation is audited)
    "list_agents": "list endpoint; browsing, not a discrete action",
    "list_models": "static allowlist lookup for a dropdown",
    "get_agent_template": "template config read for UI rendering",
    "list_slack_channels": "Slack directory lookup for a picker",
    "list_slack_users": "Slack directory lookup for a picker",
    "get_slack_config_token": "reads own token status (has/preview only)",
    "list_users": "list endpoint; browsing",
    "get_organization": "org detail read; high-frequency, low signal",
    "get_organizations": "list endpoint; browsing",
    "list_members": "list endpoint; browsing",
    "list_skills": "list endpoint; browsing",
    "get_skill": "skill detail read; low signal",
    "list_templates": "list endpoint; browsing",
    "get_template": "template detail read; low signal",
    "list_template_versions": "list endpoint; browsing",
    "list_audit_actions": "static enum lookup for the filter dropdown",
    # live log stream — SSE keepalive, not a discrete view
    "stream_agent_logs": "SSE keepalive stream; get_agent_logs covers the view",
    # OAuth handshake steps with no durable user-authenticated state
    "google_authorize_url": "OAuth handshake step; no durable state",
    "google_callback": "OAuth redirect target; no user token on the request",
    "google_token_exchange": (
        "credential mint with no expressible object (the receiving agent doesn't exist"
        " yet); the attach is audited via agent.create/update"
    ),
    # agent-key-authenticated inbound webhooks — AF-5's domain, no user actor
    "teams_webhook": "inbound agent webhook; no user actor (AF-5 domain)",
}
