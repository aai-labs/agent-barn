import type {
  Agent,
  AgentTemplate,
  Skill,
  Provider,
  ActivityEvent,
  Conversation,
} from "./types";

const AGENT_COLORS = [
  ["#4f46e5", "#7c3aed"],
  ["#0d9488", "#15803d"],
  ["#b45309", "#c2410c"],
  ["#be185d", "#9d174d"],
  ["#0e6fd4", "#0369a1"],
  ["#7c2d12", "#9a3412"],
  ["#4338ca", "#5b21b6"],
  ["#0f766e", "#0e7490"],
];

export function agentGrad(seed: number): string {
  const c = AGENT_COLORS[seed % AGENT_COLORS.length];
  return `linear-gradient(135deg, ${c[0]} 0%, ${c[1]} 100%)`;
}

export function fmtTokens(n: number): string {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toString();
}

export function fmtCost(n: number): string {
  return (
    "$" +
    n.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
}

const RAW_AGENTS = [
  {
    id: "ag_01",
    name: "Maya",
    templateVersion: 2,
    status: "RUNNING" as const,
    surface: ["slack"],
    organization_id: "org_01",
    template_id: "t_default",
    createdAt: "2026-03-14",
    updated_at: "2026-05-14T09:14:00Z",
    activity: "Posting standup recap to #eng-platform",
    activityType: "slack",
    tokensToday: 184_320,
    costToday: 4.42,
    costMonth: 87.31,
    convsToday: 23,
    toolCallsToday: 142,
    uptime: "14d 6h",
    cpu: 8,
    mem: 412,
    skills: ["slack", "jira", "gcal", "memory"],
    spark: [12, 18, 22, 17, 31, 28, 40, 36, 44, 51, 47, 62, 58, 71],
  },
  {
    id: "ag_02",
    name: "Rex",
    templateVersion: 1,
    status: "RUNNING" as const,
    surface: ["slack", "github"],
    organization_id: "org_01",
    template_id: "t_reviewer",
    createdAt: "2026-03-22",
    updated_at: "2026-05-14T09:31:00Z",
    activity: "Reviewing PR #4821 — auth-service",
    activityType: "github",
    tokensToday: 412_500,
    costToday: 9.87,
    costMonth: 192.04,
    convsToday: 41,
    toolCallsToday: 318,
    uptime: "8d 14h",
    cpu: 22,
    mem: 681,
    skills: ["github", "ripgrep", "shell", "jira"],
    spark: [40, 38, 55, 62, 48, 71, 84, 79, 92, 88, 101, 96, 112, 118],
  },
  {
    id: "ag_03",
    name: "Nova",
    templateVersion: 2,
    status: "RUNNING" as const,
    surface: ["slack"],
    organization_id: "org_01",
    template_id: "t_default",
    createdAt: "2026-02-28",
    updated_at: "2026-05-14T08:55:00Z",
    activity: "Waiting on Atlassian rate limit (retry in 38s)",
    activityType: "wait",
    tokensToday: 96_140,
    costToday: 2.31,
    costMonth: 71.18,
    convsToday: 17,
    toolCallsToday: 89,
    uptime: "21d 2h",
    cpu: 3,
    mem: 298,
    skills: ["slack", "jira", "zendesk", "memory"],
    spark: [20, 24, 19, 28, 31, 27, 35, 41, 38, 22, 18, 14, 11, 9],
  },
  {
    id: "ag_04",
    name: "Atlas",
    templateVersion: 2,
    status: "RUNNING" as const,
    surface: ["slack", "github"],
    organization_id: "org_01",
    template_id: "t_default",
    createdAt: "2026-04-02",
    updated_at: "2026-05-14T09:00:00Z",
    activity: "Drafting release notes for v4.18",
    activityType: "thinking",
    tokensToday: 220_400,
    costToday: 5.28,
    costMonth: 64.5,
    convsToday: 12,
    toolCallsToday: 87,
    uptime: "4d 9h",
    cpu: 11,
    mem: 524,
    skills: ["github", "slack", "jira", "shell"],
    spark: [10, 14, 22, 28, 31, 38, 44, 52, 49, 58, 61, 67, 72, 78],
  },
  {
    id: "ag_05",
    name: "Pip",
    templateVersion: 2,
    status: "STOPPED" as const,
    surface: ["slack"],
    organization_id: "org_01",
    template_id: "t_default",
    createdAt: "2026-04-18",
    updated_at: "2026-05-14T07:58:00Z",
    activity: "Idle — last task 14m ago",
    activityType: "idle",
    tokensToday: 18_640,
    costToday: 0.44,
    costMonth: 12.1,
    convsToday: 3,
    toolCallsToday: 11,
    uptime: "2d 1h",
    cpu: 1,
    mem: 184,
    skills: ["confluence", "slack", "memory"],
    spark: [5, 8, 12, 9, 7, 4, 11, 14, 8, 5, 3, 6, 4, 2],
  },
  {
    id: "ag_06",
    name: "Finch",
    templateVersion: 1,
    status: "RUNNING" as const,
    surface: ["slack", "teams"],
    organization_id: "org_01",
    template_id: "t_sales",
    createdAt: "2026-04-08",
    updated_at: "2026-05-14T09:20:00Z",
    activity: "Enriching 84 leads from HubSpot batch",
    activityType: "tool",
    tokensToday: 308_220,
    costToday: 7.38,
    costMonth: 121.44,
    convsToday: 6,
    toolCallsToday: 264,
    uptime: "5d 21h",
    cpu: 19,
    mem: 612,
    skills: ["hubspot", "browser", "gsheets", "memory"],
    spark: [50, 62, 71, 88, 92, 84, 99, 108, 121, 134, 128, 142, 156, 161],
  },
  {
    id: "ag_07",
    name: "Lumen",
    templateVersion: 2,
    status: "ERROR" as const,
    surface: ["slack"],
    organization_id: "org_01",
    template_id: "t_default",
    createdAt: "2026-03-30",
    updated_at: "2026-05-14T09:35:00Z",
    activity: "Pod CrashLoopBackOff — last restart 22s ago",
    activityType: "error",
    tokensToday: 4_120,
    costToday: 0.09,
    costMonth: 41.8,
    convsToday: 1,
    toolCallsToday: 4,
    uptime: "0s",
    cpu: 0,
    mem: 0,
    skills: ["pagerduty", "datadog", "slack"],
    spark: [30, 28, 35, 40, 38, 41, 36, 22, 18, 9, 4, 2, 0, 0],
  },
  {
    id: "ag_08",
    name: "Orin",
    templateVersion: 1,
    status: "RUNNING" as const,
    surface: ["slack"],
    organization_id: "org_01",
    template_id: "t_analyst",
    createdAt: "2026-03-19",
    updated_at: "2026-05-14T09:04:00Z",
    activity: "Running BigQuery: weekly retention cohorts",
    activityType: "tool",
    tokensToday: 142_080,
    costToday: 3.41,
    costMonth: 88.2,
    convsToday: 9,
    toolCallsToday: 53,
    uptime: "11d 17h",
    cpu: 14,
    mem: 488,
    skills: ["bigquery", "gsheets", "slack", "python"],
    spark: [22, 25, 31, 28, 38, 44, 41, 52, 58, 49, 61, 67, 72, 71],
  },
];

export const AGENTS: Agent[] = RAW_AGENTS.map((a, i) => ({
  ...a,
  color: agentGrad(i),
  initials: a.name.slice(0, 2).toUpperCase(),
}));

export const TEMPLATES: AgentTemplate[] = [
  {
    id: "t_default",
    slug: "default",
    name: "Default",
    description:
      "General-purpose Slack/Teams agent. Polite, factual, asks clarifying questions.",
    version: "2.0.0",
    versions: ["2.0.0", "1.4.0", "1.0.0"],
    surfaces: ["Slack", "Teams"],
    skills: ["slack", "memory"],
    files: 3,
    seededBy: "AAI Labs",
    activeAgents: 5,
  },
  {
    id: "t_reviewer",
    slug: "code-reviewer",
    name: "PR Reviewer",
    description:
      "Reads diffs, comments on style, security, and tests. Slacks digests.",
    version: "1.0.0",
    versions: ["1.0.0", "0.9.0"],
    surfaces: ["Slack", "GitHub"],
    skills: ["github", "ripgrep", "shell", "jira"],
    files: 3,
    seededBy: "AAI Labs",
    activeAgents: 1,
  },
  {
    id: "t_analyst",
    slug: "analyst",
    name: "Data Analyst",
    description:
      "Answers questions over BigQuery / Sheets, returns charts.",
    version: "1.0.0",
    versions: ["1.0.0", "0.9.0"],
    surfaces: ["Slack"],
    skills: ["bigquery", "gsheets", "slack", "python"],
    files: 3,
    seededBy: "AAI Labs",
    activeAgents: 1,
  },
  {
    id: "t_sales",
    slug: "sales-research",
    name: "Sales Research",
    description:
      "Enriches leads, drafts outbound, summarises calls into HubSpot.",
    version: "1.0.0",
    versions: ["1.0.0", "0.9.0"],
    surfaces: ["Slack", "Teams"],
    skills: ["hubspot", "browser", "gsheets", "memory"],
    files: 3,
    seededBy: "AAI Labs",
    activeAgents: 1,
  },
];

export const SKILLS: Skill[] = [
  {
    id: "slack",
    name: "Slack",
    cat: "Messaging",
    desc: "Post, react, threads, channel mgmt. Egress through proxy.",
    installs: 8,
    vetted: true,
    version: "3.1.0",
  },
  {
    id: "teams",
    name: "Microsoft Teams",
    cat: "Messaging",
    desc: "Channels, chats, adaptive cards.",
    installs: 2,
    vetted: true,
    version: "1.4.0",
  },
  {
    id: "github",
    name: "GitHub",
    cat: "Code",
    desc: "Repos, PRs, issues, checks.",
    installs: 3,
    vetted: true,
    version: "2.8.1",
  },
  {
    id: "jira",
    name: "Atlassian Jira",
    cat: "Project Mgmt",
    desc: "Issues, transitions, sprints, JQL.",
    installs: 4,
    vetted: true,
    version: "1.9.0",
  },
  {
    id: "confluence",
    name: "Confluence",
    cat: "Docs",
    desc: "Pages, spaces, search.",
    installs: 1,
    vetted: true,
    version: "1.2.0",
  },
  {
    id: "gcal",
    name: "Google Calendar",
    cat: "Calendar",
    desc: "Read/write events, find times.",
    installs: 1,
    vetted: true,
    version: "1.1.0",
  },
  {
    id: "gsheets",
    name: "Google Sheets",
    cat: "Data",
    desc: "Read, write, formula generation.",
    installs: 2,
    vetted: true,
    version: "1.0.4",
  },
  {
    id: "bigquery",
    name: "BigQuery",
    cat: "Data",
    desc: "Schema discovery + parameterised SQL.",
    installs: 1,
    vetted: true,
    version: "0.6.0",
  },
  {
    id: "hubspot",
    name: "HubSpot",
    cat: "CRM",
    desc: "Contacts, deals, sequences.",
    installs: 1,
    vetted: true,
    version: "0.3.0",
  },
  {
    id: "zendesk",
    name: "Zendesk",
    cat: "Support",
    desc: "Tickets, macros, lookups.",
    installs: 1,
    vetted: true,
    version: "0.5.0",
  },
  {
    id: "pagerduty",
    name: "PagerDuty",
    cat: "Ops",
    desc: "Incidents, ack, escalate.",
    installs: 1,
    vetted: true,
    version: "1.0.0",
  },
  {
    id: "datadog",
    name: "Datadog",
    cat: "Ops",
    desc: "Metrics, logs, monitor lookups.",
    installs: 1,
    vetted: true,
    version: "0.4.1",
  },
  {
    id: "browser",
    name: "Headless Browser",
    cat: "Tools",
    desc: "Playwright + Chromium. Auto-isolated.",
    installs: 2,
    vetted: true,
    version: "1.0.0",
  },
  {
    id: "shell",
    name: "Shell",
    cat: "Tools",
    desc: "Sandboxed POSIX shell in workspace.",
    installs: 3,
    vetted: true,
    version: "1.2.0",
  },
  {
    id: "ripgrep",
    name: "ripgrep",
    cat: "Tools",
    desc: "Fast workspace search.",
    installs: 2,
    vetted: true,
    version: "14.1.0",
  },
  {
    id: "python",
    name: "Python REPL",
    cat: "Tools",
    desc: "Workspace-scoped Python 3.12.",
    installs: 2,
    vetted: true,
    version: "3.12",
  },
  {
    id: "memory",
    name: "Long-term Memory",
    cat: "Core",
    desc: "Per-agent vector store + recall.",
    installs: 4,
    vetted: true,
    version: "1.4.0",
  },
];

export const PROVIDERS: Provider[] = [
  {
    id: "p_slack",
    name: "Slack",
    host: "slack.com, *.slack.com",
    auth: "Bearer",
    status: "active",
    keys: 3,
    lastUsed: "2s ago",
  },
  {
    id: "p_github",
    name: "GitHub",
    host: "api.github.com",
    auth: "Bearer",
    status: "active",
    keys: 2,
    lastUsed: "14s ago",
  },
  {
    id: "p_atlassian",
    name: "Atlassian",
    host: "*.atlassian.net",
    auth: "Basic",
    status: "active",
    keys: 3,
    lastUsed: "1m ago",
  },
  {
    id: "p_google",
    name: "Google Workspace",
    host: "googleapis.com",
    auth: "OAuth2",
    status: "active",
    keys: 2,
    lastUsed: "9m ago",
  },
  {
    id: "p_hubspot",
    name: "HubSpot",
    host: "api.hubapi.com",
    auth: "Bearer",
    status: "active",
    keys: 1,
    lastUsed: "3m ago",
  },
  {
    id: "p_pagerduty",
    name: "PagerDuty",
    host: "api.pagerduty.com",
    auth: "Token",
    status: "inactive",
    keys: 1,
    lastUsed: "2d ago",
  },
];

export const ACTIVITY: ActivityEvent[] = [
  {
    t: "now",
    agent: "rex",
    icon: "github",
    text: "Posted review on PR #4821",
    channel: "github.com/aai-labs/auth-svc",
    tone: "ok",
  },
  {
    t: "2s ago",
    agent: "maya",
    icon: "slack",
    text: "Replied in #eng-standups",
    channel: "#eng-standups",
    tone: "info",
  },
  {
    t: "4s ago",
    agent: "orin",
    icon: "data",
    text: "Ran BigQuery: weekly_retention_v3",
    channel: "bigquery",
    tone: "info",
  },
  {
    t: "7s ago",
    agent: "finch",
    icon: "browser",
    text: "Enriched lead: Vega Robotics (Series B)",
    channel: "hubspot",
    tone: "info",
  },
  {
    t: "12s ago",
    agent: "atlas",
    icon: "github",
    text: "Drafted release notes — v4.18",
    channel: "github.com/aai-labs/web",
    tone: "info",
  },
  {
    t: "18s ago",
    agent: "lumen",
    icon: "error",
    text: "Pod restarted — exit code 137",
    channel: "k8s",
    tone: "err",
  },
  {
    t: "24s ago",
    agent: "nova",
    icon: "jira",
    text: "Created JIRA SUP-1144 — login flake",
    channel: "support-vip",
    tone: "info",
  },
  {
    t: "31s ago",
    agent: "maya",
    icon: "tool",
    text: "Tool call: jira.transition_issue(PROJ-902)",
    channel: "jira",
    tone: "info",
  },
  {
    t: "44s ago",
    agent: "rex",
    icon: "github",
    text: "Requested changes on PR #4819",
    channel: "github",
    tone: "warn",
  },
  {
    t: "1m ago",
    agent: "orin",
    icon: "slack",
    text: "Posted chart to #growth — DAU cohort",
    channel: "#growth",
    tone: "info",
  },
  {
    t: "1m ago",
    agent: "finch",
    icon: "browser",
    text: "Browsed crunchbase.com/orgs/vega-robotics",
    channel: "browser",
    tone: "info",
  },
  {
    t: "2m ago",
    agent: "maya",
    icon: "slack",
    text: "Started standup thread in #eng-platform",
    channel: "#eng-platform",
    tone: "info",
  },
  {
    t: "2m ago",
    agent: "atlas",
    icon: "tool",
    text: "Tool call: github.list_commits(since=v4.17)",
    channel: "github",
    tone: "info",
  },
  {
    t: "3m ago",
    agent: "pip",
    icon: "slack",
    text: "Acknowledged feedback in #docs-feedback",
    channel: "#docs-feedback",
    tone: "info",
  },
];

export const CONVERSATIONS: Record<string, Conversation[]> = {
  ag_01: [
    {
      id: "c1",
      channel: "#eng-standups",
      t: "9 min ago",
      preview:
        "I'll start the thread now and follow up at 9:30 with anyone outstanding.",
      with: "Sara Chen",
      live: true,
      messages: [
        {
          who: "Sara Chen",
          t: "9:14",
          body: "Hey Maya — can you kick off today's standup and ping people who haven't posted by 9:30?",
        },
        {
          who: "agent",
          t: "9:14",
          body: "Got it. I'll start the thread now and follow up at 9:30 with anyone outstanding.",
        },
        {
          type: "tool",
          name: "slack.post_message(#eng-standups)",
          result: "ok · ts 1715508843.001",
        },
        {
          type: "tool",
          name: 'memory.recall("standup participants")',
          result: "sara, raj, mike, jenny, tomas, ana",
        },
        {
          who: "agent",
          t: "9:14",
          body: "Thread is live with the standard format. I've pulled this sprint's open ORION items per person so I can nudge if anyone goes blank.",
        },
        {
          who: "Sara Chen",
          t: "9:29",
          body: "Who's still missing?",
        },
        {
          who: "agent",
          t: "9:29",
          body: "Missing raj and tomas. I'll DM both now — should be unobtrusive.",
        },
        {
          type: "tool",
          name: "slack.post_dm(raj, tomas)",
          result: "ok",
        },
      ],
    },
    {
      id: "c2",
      channel: "#proj-orion",
      t: "31 min ago",
      preview: "Sprint goal looks healthy — 64% complete with 2 days to go.",
      with: "Raj Patel",
    },
    {
      id: "c3",
      channel: "#eng-platform",
      t: "2h ago",
      preview: "Recap posted as thread. Two blockers carried from yesterday.",
      with: "Sara Chen",
    },
    {
      id: "c4",
      channel: "DM",
      t: "Yesterday",
      preview: "Sure, I'll skip your standup tomorrow and resume Friday.",
      with: "Mike Reyes",
    },
  ],
  ag_02: [
    {
      id: "c1",
      channel: "PR #4821",
      t: "just now",
      preview:
        "Approved with two style nits and one suggestion for the test.",
      with: "Mike Reyes",
      live: true,
      messages: [
        {
          who: "Mike Reyes",
          t: "9:31",
          body: "@rex Can you take a look at this when you have a sec?",
        },
        { who: "agent", t: "9:31", body: "On it — pulling the diff." },
        {
          type: "tool",
          name: "github.get_pull_request(4821)",
          result: "12 files, +218 -84",
        },
        {
          type: "tool",
          name: 'ripgrep("TODO", auth-svc/)',
          result: "3 hits",
        },
        {
          who: "agent",
          t: "9:32",
          body: "Reviewed. Two small style things in `handlers.go` and the new test could assert on the wrapped error type. Otherwise LGTM ✅",
        },
      ],
    },
    {
      id: "c2",
      channel: "PR #4819",
      t: "1h ago",
      preview: "Requested changes — missing tests for the new branch.",
      with: "Jenny Tan",
    },
  ],
};

export function getConversations(id: string): Conversation[] {
  const agent = AGENTS.find((a) => a.id === id);
  return (
    CONVERSATIONS[id] ?? [
      {
        id: "c1",
        channel: "#general",
        t: "just now",
        preview: agent?.activity ?? "",
        with: "Sara Chen",
        live: true,
        messages: [
          {
            who: "Sara Chen",
            t: "now",
            body: `Hey ${agent?.name ?? "there"}, what are you working on?`,
          },
          {
            who: "agent",
            t: "now",
            body: agent?.activity ?? "",
          },
        ],
      },
    ]
  );
}

export function getTemplate(template_id: string): AgentTemplate | undefined {
  return TEMPLATES.find((t) => t.id === template_id);
}

export const TEMPLATE_FILES: Record<string, Record<string, string>> = {
  "t_default": {
    soul_md: `# Soul

You are a general-purpose assistant embedded in your team's workspace. You are helpful, precise, and honest.

## Core purpose
Answer questions, complete tasks, and reduce friction in the team's day.

## Values
- Accurate over fast
- Ask one clarifying question when the request is ambiguous, then act
- Never pretend to know something you don't
`,
    identity_md: `# Identity

You are an AI assistant embedded in Slack. You respond when mentioned and follow instructions carefully.

## Voice
- Clear and concise
- Friendly but not over-eager
- No filler phrases or unnecessary apologies

## Boundaries
- Do not speculate on confidential matters
- If a request falls outside your scope, say so and suggest a human
`,
    user_md: `# Users

Team members across engineering, product, and operations. Mix of technical and non-technical backgrounds.

## Tone calibration
- Match formality to the user's message
- Assume good intent; ask before refusing
- If the request is out of scope, say so and suggest who can help
`,
    tools_md: `# Tools

- slack.{post_message, post_dm, react}
- memory.{recall, store}
`,
  },

  "t_reviewer": {
    soul_md: `# Soul

You are a senior engineer who has reviewed thousands of pull requests. You care deeply about code quality, security, and maintainability — but you know a nit from a blocker.

## Core purpose
Help the team ship better code faster by catching real problems early and leaving clear, actionable feedback.

## Values
- Substance over style
- Blockers clearly separated from nits
- Explain the why, not just the what
`,
    identity_md: `# Identity

You are a PR reviewer embedded in GitHub and Slack. You are triggered by @mentions on pull requests or direct requests in allowed channels.

## Voice
- Direct and technical
- Constructive — every comment suggests a fix
- Never condescending

## Boundaries
- Do not approve PRs that omit tests on security-sensitive paths
- Do not flag formatting if a linter is configured
- Limit your review to the diff; don't rewrite surrounding code
`,
    user_md: `# Users

Software engineers opening pull requests and requesting review feedback.

## Context
- Users are technical; use precise language
- They may be protective of their code — stay constructive
- Prioritise blockers; label nits so they're not confused with blockers
`,
    tools_md: `# Tools

- github.{get_pull_request, list_files, post_review_comment, submit_review}
- ripgrep — fast codebase search
- shell — sandboxed workspace shell
- jira.{get_issue, comment}
`,
  },

  "t_analyst": {
    soul_md: `# Soul

You are a data analyst who turns raw numbers into clear stories. You are rigorous about methodology and honest about uncertainty.

## Core purpose
Answer data questions quickly and clearly. Surface insights the team didn't know to ask for.

## Values
- Show your work — include the query, not just the result
- Honest about what the data can and can't say
- Simple output over complex dashboards
`,
    identity_md: `# Identity

You are a data analyst embedded in Slack. You answer questions over the team's data infrastructure and post results as messages or charts.

## Voice
- Precise with numbers — always include units and date ranges
- Plain-English summary before the tables
- Flag caveats clearly: sample size, data freshness, known gaps

## Boundaries
- Do not write queries that modify data
- Do not surface individual-level PII; aggregate only
- Always state the time range of any metric you report
`,
    user_md: `# Users

Product, engineering, and growth team members who need data answers quickly.

## Context
- Varying SQL fluency — some can read queries, others just want the number
- Always lead with a plain-English summary before raw data
- Flag when a question can't be answered reliably with available data
`,
    tools_md: `# Tools

- bigquery — schema discovery + parameterised SQL
- gsheets.{read, write}
- python — data wrangling and chart generation
- slack.{post_message, upload_file}
`,
  },

  "t_sales": {
    soul_md: `# Soul

You are a sales researcher who is genuinely curious about companies and the people who build them. You find the signal in the noise.

## Core purpose
Help the team understand prospects deeply and reach out in a way that's relevant and human.

## Values
- Quality intel over quantity
- Respect the prospect's time — every touchpoint should earn attention
- Transparent about sources and confidence levels
`,
    identity_md: `# Identity

You are a sales researcher embedded in Slack and HubSpot. You enrich leads, draft outbound messages, and summarise calls.

## Voice
- Curious and thorough
- Concise summaries — lead with the most useful fact
- Every draft references something specific about the company; no generic templates

## Boundaries
- Do not contact prospects directly — only draft; a human sends
- Do not invent information; mark gaps explicitly
- Flag opt-out signals to the rep and stop enriching
`,
    user_md: `# Users

Account executives and SDRs who need prospect intelligence and outbound drafts.

## Context
- Time-sensitive — responses should be fast and scannable
- They know their prospects; your job is to add depth, not repeat what they know
- Flag low-confidence research clearly; don't let them send something inaccurate
`,
    tools_md: `# Tools

- hubspot.{get_contact, update_contact, create_note, get_deal}
- browser — headless Playwright for web research
- gsheets.{read, write}
- memory.{recall, store}
`,
  },
};
