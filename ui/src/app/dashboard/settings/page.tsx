"use client";

import { useState } from "react";
import { PROVIDERS } from "@/features/agents/data";
import { TemplatesPanel } from "@/features/agents/components/templates-panel";
import { SkillsPanel } from "@/features/skills/components/skills-panel";
import { PlusIcon, LockIcon, EyeIcon, ServerIcon, SearchIcon } from "@/components/icons";

type SectionKey =
  | "general"
  | "team"
  | "models"
  | "providers"
  | "templates"
  | "skills"
  | "budgets"
  | "audit"
  | "infra"
  | "advanced";

// real: true = backed by API; false = mock UI kept in code but hidden from nav
const SECTIONS: [SectionKey, string, string, boolean][] = [
  ["general",   "General",         "Your install's identity and defaults.",                         false],
  ["team",      "Team & access",   "Operators who can manage agents.",                              false],
  ["models",    "Models",          "Which LLMs your agents are allowed to use.",                   false],
  ["providers", "Integrations",    "Slack, GitHub, Jira and other third parties.",                 false],
  ["templates", "Templates",       "Reusable agent definitions.",                                   true],
  ["skills",    "Skills",          "Vetted tools your agents can call.",                           true],
  ["budgets",   "Budgets",         "Spend caps and alerts.",                                       false],
  ["audit",     "Audit log",       "Searchable history of every conversation and tool call.",      false],
  ["infra",     "Infrastructure",  "Cluster, storage, and proxy details.",                         false],
  ["advanced",  "Advanced",        "Power-user flags. Touch carefully.",                           false],
];

export default function SettingsPage() {
  const [tab, setTab] = useState<SectionKey>("templates");
  const current = SECTIONS.find((s) => s[0] === tab)!;

  return (
    <div className="max-w-[1320px] mx-auto px-10 pt-9 pb-24">
      <div className="flex gap-8 items-start">
        <aside className="w-48 flex-shrink-0 sticky top-[77px]">
          {SECTIONS.filter(([,,,real]) => real).map(([k, l]) => (
            <button
              key={k}
              className="w-full text-left px-3 py-2 rounded-lg text-[13.5px] font-medium mb-0.5 transition-colors"
              style={{
                background: tab === k ? "var(--bg-soft)" : "transparent",
                color: tab === k ? "var(--ink)" : "var(--ink-3)",
                fontWeight: tab === k ? 600 : 500,
              }}
              onClick={() => setTab(k)}
            >
              {l}
            </button>
          ))}
        </aside>

        <section className="flex-1 min-w-0">
          <h1 className="text-[28px] font-semibold tracking-tight m-0 mb-1" style={{ color: "var(--ink)" }}>
            {current[1]}
          </h1>
          <p className="text-[15px] mt-0 mb-8" style={{ color: "var(--ink-3)" }}>
            {current[2]}
          </p>

          {tab === "general" && <GeneralPanel />}
          {tab === "team" && <TeamPanel />}
          {tab === "models" && <ModelsPanel />}
          {tab === "providers" && <ProvidersPanel />}
          {tab === "templates" && <TemplatesPanel />}
          {tab === "skills" && <SkillsPanel />}
          {tab === "budgets" && <BudgetsPanel />}
          {tab === "audit" && <AuditPanel />}
          {tab === "infra" && <InfraPanel />}
          {tab === "advanced" && <AdvancedPanel />}
        </section>
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-8 py-5" style={{ borderBottom: "1px solid var(--line)" }}>
      <div className="flex-1">
        <div className="font-medium text-[14px]" style={{ color: "var(--ink)" }}>{label}</div>
        {hint && <div className="text-[13px] mt-0.5" style={{ color: "var(--ink-4)" }}>{hint}</div>}
      </div>
      <div className="flex-shrink-0 w-[280px]">{children}</div>
    </div>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 text-[13px] rounded-xl px-3.5 py-3 mb-5 leading-[1.5]"
      style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}>
      {children}
    </div>
  );
}

function TableRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 px-0 py-3.5" style={{ borderBottom: "1px solid var(--line)" }}>
      {children}
    </div>
  );
}

function Toggle({ on: initial = false }: { on?: boolean }) {
  const [v, setV] = useState(initial);
  return (
    <button
      className="relative w-10 h-6 rounded-full transition-colors flex-shrink-0"
      style={{ background: v ? "var(--ink)" : "var(--line-strong)" }}
      onClick={() => setV(!v)}
    >
      <span
        className="absolute top-[3px] w-[18px] h-[18px] rounded-full transition-transform"
        style={{
          background: "var(--bg-elev)",
          left: v ? "calc(100% - 21px)" : "3px",
        }}
      />
    </button>
  );
}

function StatusOk({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--ok)" }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--ok)" }} />
      {label}
    </span>
  );
}

function GeneralPanel() {
  return (
    <div>
      <Field label="Install name" hint="Shown in the nav and audit emails.">
        <input className="af-input" defaultValue="AAI Labs · prod" />
      </Field>
      <Field label="Time zone" hint="Used for cron triggers and standup times.">
        <select className="af-select" defaultValue="Europe/Vilnius">
          <option>Europe/Vilnius</option>
          <option>UTC</option>
          <option>America/New_York</option>
        </select>
      </Field>
      <Field label="Operator email" hint="Nightly digests, incident summaries.">
        <input className="af-input" defaultValue="ops@aai-labs.com" />
      </Field>
      <Field label="Default surface" hint="New agents go here unless told otherwise.">
        <div className="flex gap-2">
          <button className="af-btn af-btn-sm" style={{ background: "var(--ink)", borderColor: "var(--ink)", color: "var(--bg-elev)" }}>
            Slack
          </button>
          <button className="af-btn af-btn-sm">Teams</button>
        </div>
      </Field>
      <div className="mt-6">
        <button className="af-btn af-btn-primary">Save changes</button>
      </div>
    </div>
  );
}

function TeamPanel() {
  const team = [
    { init: "AT", name: "Ananiya Taye", tag: "you", role: "Admin", last: "now", color: "linear-gradient(135deg, #4338ca, #7c3aed)" },
    { init: "SC", name: "Sara Chen", tag: "", role: "Operator", last: "14m ago", color: "linear-gradient(135deg, #b45309, #c2410c)" },
    { init: "MR", name: "Mike Reyes", tag: "", role: "Operator", last: "2d ago", color: "linear-gradient(135deg, #0d9488, #15803d)" },
    { init: "JT", name: "Jenny Tan", tag: "", role: "Viewer", last: "6d ago", color: "linear-gradient(135deg, #be185d, #9d174d)" },
  ];
  return (
    <div>
      <div className="mb-4">
        <button className="af-btn af-btn-primary">
          <PlusIcon /> Invite teammate
        </button>
      </div>
      {team.map((m) => (
        <TableRow key={m.name}>
          <div className="w-8 h-8 rounded-full grid place-items-center text-[12px] font-semibold font-mono text-white flex-shrink-0" style={{ background: m.color }}>
            {m.init}
          </div>
          <div className="flex-1">
            <div className="font-medium text-[14px]" style={{ color: "var(--ink)" }}>
              {m.name} {m.tag && <span className="text-[12px] font-normal" style={{ color: "var(--ink-4)" }}>· {m.tag}</span>}
            </div>
            <div className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
              {m.role} · last active {m.last}
            </div>
          </div>
          <button className="af-btn af-btn-sm af-btn-ghost">Edit</button>
        </TableRow>
      ))}
    </div>
  );
}

function ModelsPanel() {
  return (
    <div>
      {[
        { name: "Anthropic", models: ["claude-sonnet-4.5", "claude-haiku-4.5"], age: "4d ago", ok: true },
        { name: "OpenAI", models: ["gpt-4.1", "gpt-4.1-mini"], age: "12d ago", ok: true },
        { name: "Google", models: ["gemini-2.5-pro"], age: "21d ago", ok: false },
      ].map((p) => (
        <TableRow key={p.name}>
          <div className="flex-1">
            <div className="font-medium text-[14px]" style={{ color: "var(--ink)" }}>{p.name}</div>
            <div className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
              {p.models.join(" · ")} · key rotated {p.age}
            </div>
          </div>
          {p.ok ? (
            <StatusOk label="healthy" />
          ) : (
            <span className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--warn)" }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--warn)" }} />
              95% quota
            </span>
          )}
          <button className="af-btn af-btn-sm af-btn-ghost">Manage</button>
        </TableRow>
      ))}
      <div style={{ borderTop: "1px solid var(--line)", paddingTop: 24, marginTop: 8 }}>
        <Field label="Default model" hint="Used when a template doesn't specify.">
          <select className="af-select" defaultValue="claude-sonnet-4.5">
            <option>claude-sonnet-4.5</option>
            <option>claude-haiku-4.5</option>
            <option>gpt-4.1</option>
          </select>
        </Field>
        <Field label="Fallback chain" hint="Tried in order on primary failure.">
          <input className="af-input font-mono text-[13px]" defaultValue="claude-haiku-4.5, gpt-4.1-mini" />
        </Field>
      </div>
    </div>
  );
}

function ProvidersPanel() {
  return (
    <div>
      <Hint>
        <LockIcon style={{ flexShrink: 0, marginTop: 1 }} />
        Real API keys live encrypted in Postgres and never leave the proxy pod. Agents always hold fake keys; the proxy swaps in real ones at request time.
      </Hint>
      <div className="mb-4">
        <button className="af-btn af-btn-primary">
          <PlusIcon /> Connect provider
        </button>
      </div>
      {PROVIDERS.map((p) => (
        <TableRow key={p.id}>
          <div className="flex-1">
            <div className="font-medium text-[14px]" style={{ color: "var(--ink)" }}>{p.name}</div>
            <div className="font-mono text-[12px]" style={{ color: "var(--ink-3)" }}>
              {p.host} · {p.auth} auth · {p.keys} key{p.keys > 1 ? "s" : ""} vaulted
            </div>
          </div>
          <span className="text-[12.5px]" style={{ color: "var(--ink-4)" }}>used {p.lastUsed}</span>
          {p.status === "active" ? (
            <StatusOk label="active" />
          ) : (
            <span className="inline-flex items-center gap-1.5 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--ink-4)" }} />
              inactive
            </span>
          )}
          <button className="af-btn af-btn-sm af-btn-ghost">Manage</button>
        </TableRow>
      ))}
    </div>
  );
}


function BudgetsPanel() {
  return (
    <div>
      <Field label="Monthly cap" hint="Hard cap across all agents per calendar month.">
        <input className="af-input font-mono text-[13px]" defaultValue="$2,500 / month" />
      </Field>
      <Field label="Per-agent cap" hint="Default. Each agent can override down, never up.">
        <input className="af-input font-mono text-[13px]" defaultValue="$40 / day" />
      </Field>
      <Field label="Alert at" hint="Slack-ping the operator when crossed.">
        <input className="af-input font-mono text-[13px]" defaultValue="70%, 90%, 100%" />
      </Field>
      <Field label="When cap is reached">
        <select className="af-select" defaultValue="Pause agent">
          <option>Pause agent</option>
          <option>Throttle to haiku</option>
          <option>Slack ping only</option>
        </select>
      </Field>
      <div className="mt-6">
        <button className="af-btn af-btn-primary">Save</button>
      </div>
    </div>
  );
}

function AuditPanel() {
  const rows = [
    { agent: "maya", agentName: "Maya", channel: "#eng-platform", startedAt: "09:14", duration: "4m 18s", tokens: 4882, cost: 0.117, tools: 6 },
    { agent: "rex", agentName: "Rex", channel: "PR #4821", startedAt: "09:08", duration: "2m 14s", tokens: 1820, cost: 0.043, tools: 11 },
    { agent: "orin", agentName: "Orin", channel: "#growth", startedAt: "09:02", duration: "1m 02s", tokens: 980, cost: 0.022, tools: 3 },
    { agent: "nova", agentName: "Nova", channel: "#support-vip", startedAt: "08:48", duration: "5m 41s", tokens: 6240, cost: 0.142, tools: 5 },
  ];
  return (
    <div>
      <Hint>
        <EyeIcon style={{ flexShrink: 0, marginTop: 1 }} />
        Every conversation and tool call is retained for 90 days. You can search and replay them here.
      </Hint>
      <div
        className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl mb-5"
        style={{ border: "1px solid var(--line)", background: "var(--bg-elev)" }}
      >
        <SearchIcon style={{ color: "var(--ink-4)", flexShrink: 0 }} />
        <input
          className="flex-1 text-[13.5px] outline-none bg-transparent"
          style={{ color: "var(--ink)" }}
          placeholder="Search across all conversations and tool calls…"
        />
      </div>
      {rows.map((c, i) => (
        <TableRow key={i}>
          <div className="flex-1">
            <div className="font-medium text-[14px]" style={{ color: "var(--ink)" }}>
              {c.agentName}{" "}
              <span className="font-mono text-[12px] font-normal" style={{ color: "var(--ink-4)" }}>
                · {c.channel}
              </span>
            </div>
            <div className="text-[12.5px] mt-0.5" style={{ color: "var(--ink-3)" }}>
              {c.duration} · {c.tools} tool calls · {(c.tokens / 1000).toFixed(1)}K tokens · ${c.cost.toFixed(3)}
            </div>
          </div>
          <span className="text-[12.5px]" style={{ color: "var(--ink-4)" }}>{c.startedAt}</span>
          <button className="af-btn af-btn-sm af-btn-ghost">Open</button>
        </TableRow>
      ))}
    </div>
  );
}

function InfraPanel() {
  return (
    <div>
      <Hint>
        <ServerIcon style={{ flexShrink: 0, marginTop: 1 }} />
        Agent Barn runs on your Kubernetes. You usually don&apos;t need to touch this — but here it is.
      </Hint>
      <Field label="Cluster" hint="Where agents are scheduled.">
        <div className="flex items-center gap-2.5">
          <span className="font-mono text-[13px]" style={{ color: "var(--ink)" }}>aai-prod-eu1</span>
          <StatusOk label="connected" />
          <span className="text-[12.5px]" style={{ color: "var(--ink-4)" }}>k3s 1.29.4 · 6 nodes</span>
        </div>
      </Field>
      <Field label="Storage class">
        <select className="af-select" defaultValue="local-path">
          <option>local-path</option>
          <option>longhorn</option>
          <option>aws-ebs-gp3</option>
        </select>
      </Field>
      <Field label="Default workspace size">
        <input className="af-input font-mono text-[13px] max-w-[140px]" defaultValue="10Gi" />
      </Field>
      <Field label="Egress proxy" hint="All outbound HTTP routes through mitmproxy. CA rotated 14 days ago.">
        <div className="flex items-center gap-2">
          <StatusOk label="running" />
          <button className="af-btn af-btn-sm af-btn-ghost">Rotate CA</button>
        </div>
      </Field>
      <Field label="LiteLLM" hint="Single egress for all LLM calls.">
        <div className="flex items-center gap-2">
          <StatusOk label="healthy" />
          <button className="af-btn af-btn-sm af-btn-ghost">Open LiteLLM UI</button>
        </div>
      </Field>
    </div>
  );
}

function AdvancedPanel() {
  return (
    <div>
      <Hint>
        Flags that change how the platform behaves. Most installs don&apos;t need to touch these.
      </Hint>
      <Field label="Health poll interval">
        <input className="af-input font-mono text-[13px] max-w-[140px]" defaultValue="20s" />
      </Field>
      <Field label="Audit retention">
        <input className="af-input font-mono text-[13px] max-w-[160px]" defaultValue="90 days" />
      </Field>
      <Field label="Soft-delete window" hint="How long retired agents stay restorable.">
        <input className="af-input font-mono text-[13px] max-w-[140px]" defaultValue="7 days" />
      </Field>
      <Field label="Per-agent template overrides" hint="Allow operators to fork template files per agent.">
        <Toggle on />
      </Field>
      <Field label="Telemetry to AAI Labs" hint="Aggregate, anonymised. Helps improve seeded templates.">
        <Toggle />
      </Field>
      <div
        className="mt-8 p-5 rounded-2xl"
        style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
      >
        <div className="font-semibold text-[14px] mb-3" style={{ color: "var(--err)" }}>
          Danger zone
        </div>
        <div className="flex gap-2 flex-wrap">
          <button className="af-btn">Reset all agents</button>
          <button className="af-btn">Wipe audit log</button>
          <button className="af-btn" style={{ borderColor: "var(--err)", color: "var(--err)" }}>
            Uninstall
          </button>
        </div>
      </div>
    </div>
  );
}

