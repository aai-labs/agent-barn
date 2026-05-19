"use client";

import { useState } from "react";
import Link from "next/link";
import type { Agent } from "../types";
import { getTemplate } from "../data";
import { ChevLeftIcon, PauseIcon, CogIcon } from "@/components/icons";
import { AgentAvatar } from "./agent-avatar";
import { StatusLine } from "./status-line";
import { ConversationsTab } from "./conversations-tab";
import { WorkTab } from "./work-tab";
import { AboutTab } from "./about-tab";
import { ConfigDrawer } from "./config-drawer";

interface AgentDetailPageProps {
  agent: Agent;
}

type Tab = "conversations" | "work" | "about";

export function AgentDetailPage({ agent }: AgentDetailPageProps) {
  const [tab, setTab] = useState<Tab>("conversations");
  const [configOpen, setConfigOpen] = useState(false);

  const tabs: [Tab, string, number | null][] = [
    ["conversations", "Conversations", agent.convsToday],
    ["work", "Work", null],
    ["about", "About", null],
  ];

  return (
    <div style={{ background: "var(--bg)" }}>
      <div className="max-w-[1180px] mx-auto px-10 pt-7 pb-24">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 text-[13px] mb-6 px-2 py-1 -ml-2 rounded-lg hover:bg-[var(--bg-soft)] transition-colors"
          style={{ color: "var(--ink-3)" }}
        >
          <ChevLeftIcon />
          Your team
        </Link>

        <div className="flex items-center gap-[22px] pb-8">
          <AgentAvatar agent={agent} size="xl" />
          <div className="flex-1 min-w-0">
            <h1
              className="text-[40px] font-semibold tracking-[-0.028em] m-0 mb-1 leading-[1.1]"
              style={{ color: "var(--ink)" }}
            >
              {agent.name}
            </h1>
            <div className="text-[14.5px] font-mono" style={{ color: "var(--ink-3)" }}>
              {getTemplate(agent.template_id)?.slug ?? agent.template_id}
            </div>
            <div className="flex items-center gap-2 mt-2">
              <StatusLine status={agent.status} />
              <span className="text-[13px]" style={{ color: "var(--ink-4)" }}>
                · {agent.activity}
              </span>
            </div>
          </div>
          <div className="flex gap-2">
            <button className="af-btn">
              <PauseIcon /> Pause
            </button>
            <button className="af-btn" onClick={() => setConfigOpen(true)}>
              <CogIcon /> Configure
            </button>
          </div>
        </div>

        <div
          className="flex items-center gap-1 mb-7"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          {tabs.map(([k, l, c]) => (
            <button
              key={k}
              className="ap-tab"
              data-active={tab === k}
              onClick={() => setTab(k)}
            >
              {l}
              {c != null && (
                <span className="font-mono text-[11.5px] font-medium ml-2" style={{ color: "var(--ink-4)" }}>
                  {c} today
                </span>
              )}
            </button>
          ))}
        </div>

        {tab === "conversations" && <ConversationsTab agent={agent} />}
        {tab === "work" && <WorkTab agent={agent} />}
        {tab === "about" && <AboutTab agent={agent} onConfigure={() => setConfigOpen(true)} />}
      </div>

      {configOpen && (
        <ConfigDrawer agent={agent} onClose={() => setConfigOpen(false)} />
      )}
    </div>
  );
}

