"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAgents } from "@/features/agents/hooks/use-agents";
import type { ActivityEvent } from "@/features/agents/types";
import { AgentAvatar } from "@/features/agents/components/agent-avatar";

type GroupedEvents = { label: string; events: (ActivityEvent & { id: string })[] }[];

let evCounter = 0;
const EVENT_SAMPLES: Omit<ActivityEvent & { id: string }, "id">[] = [
  { t: "now", icon: "slack", agent: "maya", text: "Replied in #eng-standups", channel: "#eng-standups", tone: "info" },
  { t: "now", icon: "github", agent: "rex", text: "Approved PR #4822 in auth-svc", channel: "github · auth-svc", tone: "ok" },
  { t: "now", icon: "data", agent: "orin", text: "Ran a query against weekly_retention_v3", channel: "bigquery", tone: "info" },
  { t: "now", icon: "browser", agent: "finch", text: "Enriched a lead from LinkedIn", channel: "hubspot", tone: "info" },
  { t: "now", icon: "github", agent: "atlas", text: "Drafted release notes for v4.19", channel: "github · web", tone: "info" },
  { t: "now", icon: "jira", agent: "nova", text: "Created JIRA SUP-1145 from a Slack DM", channel: "jira", tone: "info" },
  { t: "now", icon: "slack", agent: "maya", text: "DM'd Raj — gentle standup nudge", channel: "slack-dm", tone: "info" },
];

function makeEvent(): ActivityEvent & { id: string } {
  evCounter++;
  const s = EVENT_SAMPLES[Math.floor(Math.random() * EVENT_SAMPLES.length)];
  return { id: "ev_" + evCounter, ...s, t: "now" };
}

function ageStep(t: string): string {
  if (t === "now") return "1s ago";
  const m = t.match(/^(\d+)s ago$/);
  if (m) {
    const n = parseInt(m[1]) + 2;
    return n >= 60 ? "1m ago" : `${n}s ago`;
  }
  return t;
}

function bucketOf(t: string): string {
  if (t === "now" || /^\d+s ago$/.test(t)) return "Just now";
  if (/^\d+m ago$/.test(t)) {
    const n = parseInt(t);
    if (n < 5) return "A few minutes ago";
  }
  return "Earlier";
}

function groupEvents(events: (ActivityEvent & { id: string })[]): GroupedEvents {
  const out: GroupedEvents = [];
  let current: GroupedEvents[0] | null = null;
  for (const e of events) {
    const bucket = bucketOf(e.t);
    if (!current || current.label !== bucket) {
      current = { label: bucket, events: [] };
      out.push(current);
    }
    current.events.push(e);
  }
  return out;
}

export default function ActivityPage() {
  const router = useRouter();
  const params = useParams();
  const orgId = typeof params?.orgId === "string" ? params.orgId : "";
  const { agents } = useAgents();
  const [events, setEvents] = useState<(ActivityEvent & { id: string })[]>(() =>
    EVENT_SAMPLES.map((e, i) => ({ ...e, id: "init_" + i }))
  );
  const [filterAgent, setFilterAgent] = useState("all");

  useEffect(() => {
    const id = setInterval(() => {
      setEvents((prev) => {
        const aged = prev.map((e) => ({ ...e, t: ageStep(e.t) }));
        return [makeEvent(), ...aged].slice(0, 60);
      });
    }, 2200);
    return () => clearInterval(id);
  }, []);

  const filtered =
    filterAgent === "all" ? events : events.filter((e) => e.agent === filterAgent);
  const groups = groupEvents(filtered);

  return (
    <div className="max-w-[75rem] mx-auto px-10 pt-9 pb-24">
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-4xl font-semibold tracking-[-0.028em] m-0 leading-[1.15]" style={{ color: "var(--ink)" }}>
            Activity
          </h1>
          <p className="text-base mt-1.5 max-w-[40rem]" style={{ color: "var(--ink-3)" }}>
            A live feed of everything your AI team is doing — across all surfaces, in plain English.
          </p>
        </div>
        <select
          className="af-select"
          style={{ width: "auto", fontSize: "0.844rem", padding: "0.5rem 0.75rem" }}
          value={filterAgent}
          onChange={(e) => setFilterAgent(e.target.value)}
        >
          <option value="all">Everyone</option>
          {agents.map((a) => (
            <option key={a.id} value={a.name.toLowerCase()}>
              {a.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-6">
        {groups.map((g, gi) => (
          <div key={gi}>
            <div
              className="text-xs uppercase tracking-[0.08em] font-semibold mb-3"
              style={{ color: "var(--ink-4)" }}
            >
              {g.label}
            </div>
            <div className="af-card overflow-hidden">
              {g.events.map((e, i) => {
                const realAgent = agents.find((a) => a.name.toLowerCase() === e.agent);
                const avatarAgent = realAgent ?? { id: e.agent, name: e.agent };
                const isNew = i === 0 && gi === 0;
                return (
                  <div
                    key={e.id}
                    className="flex items-center gap-3.5 px-5 py-3.5 cursor-default transition-colors"
                    style={{
                      borderBottom: i < g.events.length - 1 ? "1px solid var(--line)" : undefined,
                      background: isNew ? "var(--bg-soft)" : undefined,
                    }}
                    onClick={() => realAgent && router.push(`/dashboard/${orgId}/agents/${realAgent.id}`)}
                    onMouseEnter={(el) => {
                      (el.currentTarget as HTMLElement).style.background = "var(--bg-soft)";
                    }}
                    onMouseLeave={(el) => {
                      (el.currentTarget as HTMLElement).style.background = isNew
                        ? "var(--bg-soft)"
                        : "transparent";
                    }}
                  >
                    <AgentAvatar agent={avatarAgent} size="sm" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm" style={{ color: "var(--ink)" }}>
                        <b className="font-semibold">{realAgent?.name ?? e.agent}</b>{" "}
                        {e.text.charAt(0).toLowerCase() + e.text.slice(1)}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-xs" style={{ color: "var(--ink-4)" }}>{e.t}</span>
                        <span style={{ color: "var(--ink-5)" }}>·</span>
                        <span className="font-mono text-xs" style={{ color: "var(--ink-4)" }}>
                          {e.channel}
                        </span>
                      </div>
                    </div>
                    <ToneDot tone={e.tone} />
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ToneDot({ tone }: { tone: ActivityEvent["tone"] }) {
  const color =
    tone === "ok"
      ? "var(--ok)"
      : tone === "warn"
      ? "var(--warn)"
      : tone === "err"
      ? "var(--err)"
      : "transparent";
  if (tone === "info") return null;
  return (
    <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: color }} />
  );
}
