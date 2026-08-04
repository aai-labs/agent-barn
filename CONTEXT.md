# Agent Farm

Agent Farm manages organization-owned AI agents that operate in Slack, Microsoft Teams, or Telegram through a selected runtime and a versioned configuration.

## Language

**Organization**:
The tenant boundary that owns agents, templates, skills, memberships, and organization-scoped activity.
_Avoid_: workspace, tenant account

**Organization Creator**:
The user who originally created an Organization, retained as immutable provenance. Creation grants an Organization Owner Membership, but later ownership changes do not change the Organization Creator.
_Avoid_: Organization Owner, current owner

**Organization Status**:
The platform-controlled lifecycle state of an Organization: Active or Suspended. Suspension preserves the Organization and its Memberships while disabling organization-scoped access and runtime activity until reactivation.
_Avoid_: deleted Organization, disabled Membership

**Organization Creation Limit**:
The deployment-configured maximum number of non-deleted Organizations attributed to one Organization Creator. Active and Suspended Organizations both count, and Platform Privilege does not bypass the limit.
_Avoid_: Membership limit, ownership limit, Platform Administrator quota

**Platform Administrator**:
A user with platform-level authority to administer Agent Farm outside any single Organization. A Platform Administrator may also have normal Memberships, but platform authority is separate from Organization Membership authority.
_Avoid_: superuser, super admin, global role

**Platform Privilege**:
The platform-level grant that makes a user a Platform Administrator.
_Avoid_: global Membership, Organization Role, default Organization ownership

**Platform Resource**:
A global resource owned by Agent Farm itself rather than by an Organization.
_Avoid_: default Organization resource, shared tenant data

**Platform View**:
The product mode where a Platform Administrator manages Platform Resources and Platform Oversight Data without an Active Organization or direct access to Organization-owned resources.
_Avoid_: default Organization, admin Organization, global workspace

**Platform Oversight Data**:
An explicitly allowlisted, read-only representation of user, Organization, Membership, Agent, activity, model-usage, and platform-borne cost facts used for cross-Organization governance. It excludes tenant content, configuration payloads, credentials, Secrets, and raw telemetry.
_Avoid_: Organization View, impersonation, unrestricted tenant access

**Organization View**:
The product mode where a user, including a Platform Administrator with Memberships, operates through Membership authority inside an Active Organization.
_Avoid_: tenant view, platform view

**Active Organization**:
The single Organization currently selected for organization-scoped product behavior. Platform View has no Active Organization.
_Avoid_: default Organization, primary Organization

**Membership**:
The relationship between a user and an organization, carrying exactly one organization role.
_Avoid_: organization user, user organization

**Organization Role**:
A Membership's fixed organization-scoped authority. The roles are Organization Owner, Organization Admin, and Organization Member; an Organization can have at most one Organization Owner.
_Avoid_: Agent Access Role, user role, global role, superuser

**Permission**:
A named capability granted through an Organization Role or Agent Access Role and evaluated for the active Organization and, when applicable, one Agent.
_Avoid_: role check, global permission

**Agent Access Role**:
A permission-backed role governing what one Membership may do with one Agent. The locked defaults are Agent Viewer, Agent Editor, and Agent Owner; Organizations may define custom Agent Access Roles.
_Avoid_: Organization Role, Agent ownership, access level

**Agent Access**:
The relationship assigning one Agent Access Role to one Membership for one Agent. Organization Owner/Admin authority over all Agents is implicit and is not an Agent Access relationship.
_Avoid_: Agent ownership, Organization Membership

**Agent General Access**:
An Agent-scoped setting granting one Agent Access Role to all current and future accepted Organization Members, additive with explicit Agent Access. It is either Restricted or All Organization Members; new and migrated Agents are Restricted. Pending and removed Memberships receive nothing from it, and it never reduces Permissions granted by explicit Agent Access.
_Avoid_: General access, public Agent, shared Agent

**Agent Creator**:
The user who originally created an Agent, retained as immutable provenance. Creation grants explicit Agent Owner access, but creator identity is not itself an authorization source.
_Avoid_: Organization Owner, permanent Agent authority

**Agent**:
An organization-owned AI worker configured from a pinned template version and executed by one runtime on one chat platform.
_Avoid_: bot, pod

**Configured Model**:
The model currently selected for an Agent. It describes present configuration, not necessarily every model the Agent used historically.
_Avoid_: model usage, observed model

**Observed Model Usage**:
The models and token usage attributed to Agent executions during a defined reporting period. It may include multiple models and may differ from the Agent's current Configured Model.
_Avoid_: configured model, current model

**Runtime**:
The implementation that executes an agent. Agent Farm currently supports Hermes and OpenClaw.
_Avoid_: platform

**Platform**:
The chat system through which an agent interacts with people. Agent Farm currently supports Slack, Microsoft Teams, and Telegram.
_Avoid_: runtime

**Template**:
A versioned Markdown configuration lineage used to create and run agents. Predefined templates are Platform Resources; custom templates belong to one Organization.
_Avoid_: prompt, preset

**Template Version**:
A numbered configuration within a template lineage. An agent pins a specific version rather than following the latest automatically.
_Avoid_: template revision

**Draft Template Version**:
An unpublished, in-progress next version of a Platform Template lineage, editable only by a Platform Administrator and invisible to every Organization. A lineage has at most one Draft Template Version at a time; publishing it produces the next immutable Platform Template Version.
_Avoid_: unpublished template, WIP template

**Template Restore**:
A Platform Administrator action that seeds the Draft Template Version from any selected immutable Platform Template Version. Publishing the restored draft creates the next version in the lineage; it never mutates or removes the selected historical version.
_Avoid_: version pointer switch, destructive rollback

**Fork Baseline Version**:
The Platform Template Version an Organization Template fork was last synced to. Set when the fork is created and advanced each time a Template Update is applied; distinct from the fork's original creation point once updates have happened.
_Avoid_: forked-from version, origin template

**Template Update**:
The manual, all-or-nothing action that rebases an Organization Template fork onto its Fork Baseline's newer Platform Template Version, reapplying the fork's previously-diverged fields on top of the new baseline as a new Organization Template Version.
_Avoid_: template merge, template sync

**Skill**:
A packaged set of agent instructions or references that can be assigned to an agent and required by a template.
_Avoid_: integration, tool

**Agent Secret**:
An encrypted, provider-specific credential payload assigned to one agent so its runtime can access an external service. May hold its own encrypted content or reference a Shared Credential.
_Avoid_: skill, application secret

**Shared Credential**:
An encrypted, provider-specific credential payload owned by an organization and reusable across agents. Admins manage shared credentials; any org member can attach one to an agent.
_Avoid_: org secret, global credential

**Integration**:
An external service made available to an agent through an Agent Secret and runtime-specific configuration.
_Avoid_: credential

**Conversation Message**:
An inbound or outbound chat message ingested from an agent runtime and associated with a channel, direct message, session, and optional thread.
_Avoid_: conversation

**Telemetry Event**:
A runtime-originated operational fact received through Ingest and used to maintain product activity records such as Conversation Messages and Tool Calls.
_Avoid_: domain event, outbox message, audit event

**Tool Call**:
An ingested record of one external tool execution by an agent, with pending, success, or error status.
_Avoid_: integration call

**Domain Event**:
An immutable, typed business fact that occurred at Platform or Organization scope and may be handled internally by Agent Farm.
_Avoid_: outbox row, telemetry event, audit log

**Event Scope**:
The boundary within which a Domain Event occurred: Platform or Organization. Organization-scoped events identify exactly one Organization; Platform-scoped events identify none.
_Avoid_: default Organization, global tenant

**Outbox Message**:
The durable PostgreSQL record of a committed Domain Event that represents publication intent without depending on a broker-specific transport.
_Avoid_: domain event, queue message, webhook event

**Actor Identity**:
The typed principal responsible for a Domain Event, such as a Membership, User, System process, or Runtime.
_Avoid_: user ID, owner, creator

**Subject Identity**:
The typed resource or entity that a Domain Event is about.
_Avoid_: agent ID, target, object

**Event Payload**:
The bounded, secret-safe JSON object carrying event-specific domain data for a Domain Event.
_Avoid_: serialized model, database row snapshot, metadata

**Event Delivery**:
A durable, handler-specific delivery record for one Domain Event and one intended Event Handler. Its lifecycle is pending, enqueued, processing, succeeded, or dead-lettered; retry attempts do not define its identity.
_Avoid_: retry attempt, outbox message, failed event

**Dead-lettered Event Delivery**:
An Event Delivery that reached terminal failure and has no automatic retry remaining.
_Avoid_: failed event, failed message

**Event Handler**:
A named internal consumer of one or more Domain Events, with a stable identity used for delivery tracking and idempotency. Event Handler names are durable contracts once Event Deliveries can reference them.
_Avoid_: worker, callback, subscriber

**Security Audit Record**:
A durable, immutable compliance artifact that records a security-relevant fact, usually produced as a projection from a Domain Event. It survives deletion of the Organization, user, Membership, Agent, or other subject it describes.
_Avoid_: domain event, audit event, log line

**Ingest**:
The separately served, authenticated telemetry path through which agent runtimes report conversation messages and tool-call state to Agent Farm.
_Avoid_: webhook

## Relationships

- An **Organization** has many **Memberships**, **Agents**, **Templates**, custom **Skills**, and **Shared Credentials**.
- An **Organization** has one immutable **Organization Creator**, and creation grants that user the initial Organization Owner **Membership**.
- **Platform Oversight Data** may describe Organizations and their resources but never establishes an Active Organization or grants Organization authority.
- A **Membership** links one user to one **Organization** with one **Organization Role**.
- An **Organization Role** grants **Permissions** for Organization capabilities.
- An **Agent Access Role** grants **Permissions** for one Agent aggregate.
- An **Agent** belongs to one **Organization**, has one original **Agent Creator**, pins one **Template Version**, uses one **Runtime**, and connects to one **Platform**.
- An **Agent** has one current **Configured Model** and may have **Observed Model Usage** for multiple models over time.
- A **Membership** may have **Agent Access** to many Agents, and each relationship carries one **Agent Access Role**; creating an Agent grants its creator explicit Agent Owner access without transferring Organization ownership.
- An **Agent** has one **Agent General Access** setting whose Permissions combine with (never subtract from) explicit Agent Access grants.
- A **Template Version** may require multiple **Skills**.
- A Platform Template lineage has at most one **Draft Template Version**, authored only by a **Platform Administrator**; publishing it exposes the next Platform Template Version to every Organization.
- A **Platform Administrator** can inspect any immutable Platform Template Version and use a **Template Restore** to seed a new Draft Template Version from it; the restore leaves version history and existing Agent pins unchanged.
- An Organization Template fork tracks a **Fork Baseline Version**; a **Template Update** rebases the fork onto its origin's newer Platform Template Version while preserving the fork's diverged fields.
- Editing an Agent's configuration from the Agent's own screen forks (or updates the existing fork of) its pinned Platform Template and repins that one Agent to the resulting Organization Template Version; other Agents still pinned to the prior version are unaffected. Running agents reject configuration updates, so the Agent must be stopped first.
- An **Agent** may have multiple **Skills** and **Agent Secrets**.
- Agent runtimes send **Telemetry Events** through **Ingest**, where they become **Conversation Messages** or **Tool Calls**.
- A **Domain Event** has one **Event Scope**. A committed Domain Event is persisted as one **Outbox Message** and may have many **Event Deliveries**, one per intended handler.
- A **Security Audit Record** may be produced from a **Domain Event**, but it is not itself the Domain Event.

## Flagged ambiguities

- The API field `agent_type` represents the **Runtime**, while product documentation uses “runtime.” Treat Runtime as the domain term; changing the API field requires a compatibility decision.
- The persisted field `openclaw_msg_id` stores the runtime-external message identifier for both OpenClaw and Hermes messages. Its name is narrower than its current meaning.
- “Integration” is sometimes used for both the external service and its credential. Use **Integration** for the service and **Agent Secret** for the stored credential payload.
- “Owner” names both an Organization Role and a default Agent Access Role. Use **Organization Owner** for tenant governance and **Agent Owner** for full authority over one Agent.
