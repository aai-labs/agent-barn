# Conversations, communications, and operations

The product API exposes more than Agent lifecycle calls. Use the [operation catalog](/api/v1/discovery) or [OpenAPI](/api/v1/openapi.json) for every method and request schema on this deployment.

- Activity summaries and feeds are under `/organizations/{organization_id}/activity`.
- Agent conversation history, tool calls, log snapshots, and the log stream are under `/organizations/{organization_id}/agents/{agent_id}/...`. Web Chat endpoints let an authorized user inspect and send messages to a visible Agent.
- Organization Agent Settings are under `/organizations/{organization_id}/agent-settings`; they require Organization permissions.
- Agent Webhooks are managed through the Agent-scoped product routes. Public webhook delivery uses its own ingress authentication, not a Personal API Key.
- Communications Connection routes expose setup and operational controls. Runtime/provider callbacks and the separate Communications gateway retain their protocol-specific credentials.
- Agent restore points are managed through Agent-scoped routes and existing Agent Permissions.
- Cost endpoints include Organization summaries and Agent costs. Platform cost and LLM budget routes require current Platform Administrator authority.

A Personal API Key reaches every user-authenticated Product API operation through the shared authentication dependency. A read-only key cannot make write requests. Tenant and Agent Access checks remain the same as for a browser session. Consult each operation's OpenAPI security declaration and response model before calling it.
