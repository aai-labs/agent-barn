# Agent Farm

Agent Farm manages organization-owned AI agents that operate in Slack or Microsoft Teams through a selected runtime and a versioned configuration.

## Language

**Organization**:
The tenant boundary that owns agents, templates, skills, memberships, and organization-scoped activity.
_Avoid_: workspace, tenant account

**Membership**:
The relationship between a user and an organization, carrying exactly one organization role.
_Avoid_: organization user, user organization

**Organization Role**:
A membership's organization-scoped authority. The predefined roles are owner, admin, and member; an organization can have at most one owner.
_Avoid_: user role, global role, superuser

**Permission**:
A named capability granted through an Organization Role and evaluated for a specific organization, action, and when applicable resource.
_Avoid_: role check, global permission

**Permission Scope**:
The resource boundary of a role's Permission grant: organization covers all matching resources in that Organization, while assigned covers only Agent aggregates linked through Agent Access.
_Avoid_: global scope, tenant bypass

**Agent Access**:
The relationship that makes an Agent assigned to a Membership. A member sees and may exercise assigned-agent permissions only for Agents they created or were explicitly granted access to.
_Avoid_: agent ownership, organization membership

**Agent Creator**:
The user who originally created an Agent, retained as provenance rather than ownership or current access.
_Avoid_: agent owner, agent manager

**Agent**:
An organization-owned AI worker configured from a pinned template version and executed by one runtime on one chat platform.
_Avoid_: bot, pod

**Runtime**:
The implementation that executes an agent. Agent Farm currently supports Hermes and OpenClaw.
_Avoid_: platform

**Platform**:
The chat system through which an agent interacts with people. Agent Farm currently supports Slack and Microsoft Teams.
_Avoid_: runtime

**Template**:
An organization-scoped lineage of versioned Markdown configuration used to create and run agents.
_Avoid_: prompt, preset

**Template Version**:
A numbered configuration within a template lineage. An agent pins a specific version rather than following the latest automatically; system-managed predefined version 1 can be refreshed in place during startup seeding.
_Avoid_: template revision

**Skill**:
A packaged set of agent instructions or references that can be assigned to an agent and required by a template.
_Avoid_: integration, tool

**Agent Secret**:
An encrypted, provider-specific credential payload assigned to one agent so its runtime can access an external service.
_Avoid_: skill, application secret

**Integration**:
An external service made available to an agent through an Agent Secret and runtime-specific configuration.
_Avoid_: credential

**Conversation Message**:
An inbound or outbound chat message ingested from an agent runtime and associated with a channel, direct message, session, and optional thread.
_Avoid_: conversation

**Tool Call**:
An ingested record of one external tool execution by an agent, with pending, success, or error status.
_Avoid_: integration call

**Ingest**:
The separately served, authenticated telemetry path through which agent runtimes report conversation messages and tool-call state to Agent Farm.
_Avoid_: webhook

## Relationships

- An **Organization** has many **Memberships**, **Agents**, **Templates**, and custom **Skills**.
- A **Membership** links one user to one **Organization** with one **Organization Role**.
- An **Organization Role** grants **Permissions** with a **Permission Scope** within its Organization.
- An **Agent** belongs to one **Organization**, has one original **Agent Creator**, pins one **Template Version**, uses one **Runtime**, and connects to one **Platform**.
- A **Membership** may have **Agent Access** to many Agents; creating an Agent establishes access without making the creator its owner.
- A **Template Version** may require multiple **Skills**.
- An **Agent** may have multiple **Skills** and **Agent Secrets**.
- An Agent runtime sends **Conversation Messages** and **Tool Calls** through **Ingest**.

## Flagged ambiguities

- The API field `agent_type` represents the **Runtime**, while product documentation uses “runtime.” Treat Runtime as the domain term; changing the API field requires a compatibility decision.
- The persisted field `openclaw_msg_id` stores the runtime-external message identifier for both OpenClaw and Hermes messages. Its name is narrower than its current meaning.
- “Integration” is sometimes used for both the external service and its credential. Use **Integration** for the service and **Agent Secret** for the stored credential payload.
