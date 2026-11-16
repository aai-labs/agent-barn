# Agent Barn workflow walkthroughs

Start with one Agent and a bounded task. These examples describe configuration
and checks based on the repository's contracts and bundled templates. They are
not recorded end-to-end executions or promises about model quality.

Complete the [local quick start](../README.md#quick-start), create an Organization,
and sign in with permission to configure its Agents. Use test projects and
repositories for your first tool actions. Model calls can incur provider charges.

## Run OpenClaw and Hermes together

1. Hire an Agent, select its Template, model, and either OpenClaw or Hermes.
2. Attach the Skills and credentials required for that Agent's role.
3. Start it, then repeat for another Agent with the other runtime.
4. Add a Communication Connection to each Agent, or use Web Chat, and send a
   small request that you can check yourself.
5. Review each Agent's lifecycle status, conversation, tool calls, and Costs tab.

Both runtimes run as separate Agent pods managed by Agent Barn. Runtime choice
does not imply identical features: Hermes supports the configured command-approval
mode; OpenClaw does not expose that same user-configurable control. Do not assume
that every action waits for human approval.

See [runtime assembly and approval behavior](architecture/runtime-and-deployment.md)
and [Agent lifecycle](features/agents.md) for the current boundaries.

## Turn a Slack request into a Jira task

1. Hire an Agent with the **Jira Task Helper** template and a supported model.
2. Attach a Jira credential limited to a test project and the required Jira Skill.
3. Add a Slack Communication Connection using the platform's setup instructions,
   then admit the intended channels/users through the Agent's access policy.
4. Message the Agent with the Jira project key and a small request, for example:
   “Draft a task in DEMO to update the onboarding checklist. Ask me before filing.”
5. Review the proposed summary and description. Confirm only when they are right.
6. Check the returned Jira issue key in Jira and inspect the Agent's conversation
   and tool-call history. Check that the selected project and fields match.

The bundled template instructs the Agent to confirm before creating or changing
an issue. This is a model instruction, not a substitute for provider permissions
or an independent authorization gate.

[Slack setup](https://agentbarn.dev/guides/platforms/slack) ·
[Jira setup](https://agentbarn.dev/guides/integrations/jira) ·
[Jira Task Helper instructions](../api/domains/templates/predefined/seeds/jira-task-helper/agents.md) ·
[Integration and credential contract](features/integrations.md).

## Review a pull request

1. Hire an Agent with the **PR Reviewer** template.
2. Give it the Skill and credential for your code host, scoped to a test repository.
3. Connect the messaging platform your team uses.
4. Send a pull-request URL with a focused request: “Review this diff for correctness.
   Link each finding to the affected code; explain any uncertainty.”
5. Inspect its tool calls, compare its findings with the diff, and decide which
   suggestions to accept. The review does not authorize merging or deploying.

The available code-host integrations and credential behavior are documented in
[Integrations](features/integrations.md). Template behavior and version pinning
are documented in [Templates and Skills](features/templates-and-skills.md).

## Prepare a source-linked team report

1. Hire a **General Purpose** Agent and connect the source systems needed for
   one report, such as Jira and GitHub. Prefer read-only provider access where
   that is sufficient for the task.
2. Ask for a bounded report: “Summarize this week's completed work in DEMO.
   Link to the source issues and pull requests. List missing or uncertain data.”
3. Inspect source links, the reporting period, and any totals before sharing it.
4. Check conversation and tool-call history and the Agent's cost after sync.
5. Only after the manual request is useful should you consider a scheduled run.
   Follow [Agent workflows](features/agent-workflows.md) for workflow configuration,
   review behavior, execution limits, and recovery.

The [README UI preview](../README.md) uses synthetic responses from the workflow
browser fixtures. Its completion status and timing are illustrative.

## Track per-agent model costs

Each Agent's LiteLLM virtual key lets Agent Barn attribute imported model-call
records to that Agent and its Organization.

1. Send a small request to an Agent and note the time and selected model.
2. Open that Agent's **Costs** tab and choose a date range covering the request.
3. Check model-call records and spend after synchronization. The local cost-sync
   service and deployed CronJob normally run every 15 minutes; provider and sync
   failures can delay records or lead to later corrections.
4. Compare the Agent's activity with those records. A missing record is not proof
   that the request was free. Reconcile billing with the model provider.

Per-agent spend is not a guaranteed exact cost for one business task: a task can
include multiple model calls and other expenses. See [Costs](features/costs.md)
for attribution, synchronization, spend-limit enforcement, and known gaps.

## Data flow and access

Self-hosting keeps the control plane and its database in infrastructure you
operate. Model requests and connected tool calls can leave that infrastructure.
Optional product analytics are described in [usage analytics](../README.md#usage-analytics).
Agent Access and provider credentials serve different purposes; consult the
[access-control contract](features/rbac/IMPLEMENTATION-BRIEF.md) before changing
who can read or operate an Agent.
