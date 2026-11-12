# Workflows are Organization-owned; Agents run them

Status: Accepted
Date: 2026-11-12
Origin: [AF-439](https://aai-labs.atlassian.net/browse/AF-439)

Workflows were created on, owned by and addressed through one Agent. Workflows are now a first-party feature of the platform that does not depend on Agents: a Workflow belongs to the Organization and is managed at the Organization level, and an Agent is the runner of a workflow run, not the parent of the workflow. Because that relationship is composition rather than parent and child, no workflow route depends on an Agent in its URL: workflows have their own router, and the Agent that runs a run is passed as data in the request and stored on the run.

Some workflows are meant for a particular Agent. A workflow can therefore name a default Agent, which is preselected when a run starts; the person starting the run can still choose another Agent ("Run as").

## Considered alternatives

- **Keep workflows owned by an Agent.** Rejected: it makes a platform feature depend on Agents and models the runner as the owner.
- **Move definitions to the Organization but keep run routes nested under the Agent**, with the Agent in the path naming the runner. Rejected: a workflow reference would still depend on an Agent's URL; the Agent is data about a run and is passed in the payload.
- **Delete the workflows of already deleted Agents during the migration.** Rejected: the workflow itself is kept as an Organization workflow, and its runs are shown against an archived Agent with no navigation to it.

## Consequences

- Any accepted Member reads and creates workflows; the creator and Organization Owners and Admins change or archive them. Runs follow the Agent that runs them (`agent.update` to act, `agent.read` to see). The [workflow specification](../features/agent-workflows.md#ownership-and-authority) owns the contract and the [RBAC brief](../features/rbac/IMPLEMENTATION-BRIEF.md) its enforcement.
- The Agent-nested workflow routes are removed rather than kept alongside the new ones. Workflows are experimental and not in use, so the removal does not wait for a new major API version.
- Workflows are created and managed on the Organization's Workflows page; an Agent's page shows only the runs that Agent ran.
