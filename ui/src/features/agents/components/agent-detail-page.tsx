"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAgent } from "../hooks/use-agent";
import { useAgentHealth } from "../hooks/use-agent-health";
import { useStartAgent } from "../hooks/use-start-agent";
import { useStopAgent } from "../hooks/use-stop-agent";
import { usePairAgent } from "../hooks/use-pair-agent";
import { ChevLeftIcon, PauseIcon, PlayIcon, CogIcon, LinkIcon } from "@/components/icons";
import { AppErrorState } from "@/components/app-error-state";
import { toastError } from "@/shared/toast";
import { AgentAvatar } from "./agent-avatar";
import { StatusLine } from "./status-line";
import { ConversationsTab } from "./conversations-tab";
import { ToolCallsTab } from "./tool-calls-tab";
import { WorkTab } from "./work-tab";
import { AboutTab } from "./about-tab";
import { ConfigDrawer } from "./config-drawer";
import type { Agent } from "../schemas";

interface AgentDetailPageProps {
  agentId: string;
}

type Tab = "conversations" | "tool-calls" | "work" | "about";
const VALID_TABS: Tab[] = ["conversations", "tool-calls", "work", "about"];

function HeaderSkeleton() {
  return (
    <div className="flex items-center gap-5.5 pb-8 animate-pulse">
      <div className="w-18 h-18 rounded-full flex-shrink-0" style={{ background: "var(--bg-soft)" }} />
      <div className="flex-1 flex flex-col gap-2">
        <div className="h-9 w-48 rounded-lg" style={{ background: "var(--bg-soft)" }} />
        <div className="h-3.5 w-32 rounded-md" style={{ background: "var(--bg-soft)" }} />
        <div className="h-3.5 w-20 rounded-md" style={{ background: "var(--bg-soft)" }} />
      </div>
    </div>
  );
}

export function AgentDetailPage({ agentId }: AgentDetailPageProps) {
  const { agent, isLoading, error, refetch } = useAgent(agentId);
  const { health } = useAgentHealth(agentId, agent?.status === "RUNNING");
  const stopAgent = useStopAgent();
  const startAgent = useStartAgent();
  const searchParams = useSearchParams();
  const router = useRouter();
  const rawTab = searchParams.get("tab");
  const tab: Tab = VALID_TABS.includes(rawTab as Tab) ? (rawTab as Tab) : "conversations";
  const [configOpen, setConfigOpen] = useState(false);
  const [pairOpen, setPairOpen] = useState(false);

  const tabs: [Tab, string][] = [
    ["conversations", "Conversations"],
    ["tool-calls", "Tool calls"],
    ["work", "Work"],
    ["about", "About"],
  ];

  const isRunning = agent?.status === "RUNNING";

  return (
    <div style={{ background: "var(--bg)" }}>
      <div className="max-w-[73.75rem] mx-auto px-10 pt-7 pb-24">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 text-[0.8125rem] mb-6 px-2 py-1 -ml-2 rounded-lg hover:bg-[var(--bg-soft)] transition-colors"
          style={{ color: "var(--ink-3)" }}
        >
          <ChevLeftIcon />
          Your team
        </Link>

        {isLoading && <HeaderSkeleton />}

        {error && (
          <AppErrorState
            error={error}
            title="We couldn't load this agent"
            description="The agent may have been deleted or is unavailable."
            onRetry={() => { void refetch(); }}
            retryLabel="Retry"
            className="min-h-[15rem] p-0"
          />
        )}

        {agent && (
          <>
            <div className="flex items-center gap-5.5 pb-8">
              <AgentAvatar agent={agent} size="xl" />
              <div className="flex-1 min-w-0">
                <h1
                  className="text-[2.5rem] font-semibold tracking-[-0.028em] m-0 mb-1 leading-[1.1]"
                  style={{ color: "var(--ink)" }}
                >
                  {agent.name}
                </h1>
                {agent.model && (
                  <div className="text-[0.906rem] font-mono" style={{ color: "var(--ink-3)" }}>
                    {agent.model}
                  </div>
                )}
                <div className="mt-2">
                  <StatusLine status={agent.status} health={health} />
                </div>
              </div>
              <div className="flex gap-2">
                {isRunning && (
                  <button
                    className="af-btn"
                    disabled={stopAgent.isPending}
                    onClick={() => { void stopAgent.mutateAsync(agent.id).catch(toastError); }}
                  >
                    <PauseIcon /> {stopAgent.isPending ? "Pausing…" : "Pause"}
                  </button>
                )}
                {!isRunning && (
                  <button
                    className="af-btn"
                    disabled={startAgent.isPending}
                    onClick={() => { void startAgent.mutateAsync(agent.id).catch(toastError); }}
                  >
                    <PlayIcon /> {startAgent.isPending ? "Starting…" : "Start"}
                  </button>
                )}
                {isRunning && (
                  <button className="af-btn" onClick={() => setPairOpen(true)}>
                    <LinkIcon /> Pair
                  </button>
                )}
                <button className="af-btn" onClick={() => setConfigOpen(true)}>
                  <CogIcon /> Configure
                </button>
              </div>
            </div>

            <div
              className="flex items-center gap-1 mb-7"
              style={{ borderBottom: "1px solid var(--line)" }}
            >
              {tabs.map(([k, l]) => (
                <button
                  key={k}
                  className="ap-tab"
                  data-active={tab === k}
                  onClick={() => router.replace(`?tab=${k}`, { scroll: false })}
                >
                  {l}
                </button>
              ))}
            </div>

            {tab === "conversations" && <ConversationsTab agent={agent} />}
            {tab === "tool-calls" && <ToolCallsTab agent={agent} />}
            {tab === "work" && <WorkTab agent={agent} />}
            {tab === "about" && <AboutTab agent={agent} onConfigure={() => setConfigOpen(true)} />}
          </>
        )}
      </div>

      {configOpen && agent && (
        <ConfigDrawer agent={agent} onClose={() => setConfigOpen(false)} />
      )}

      {pairOpen && agent && (
        <PairDialog agent={agent} onClose={() => setPairOpen(false)} />
      )}
    </div>
  );
}

function PairDialog({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const pairAgent = usePairAgent();
  const [platform, setPlatform] = useState("slack");
  const [code, setCode] = useState("");

  async function handleSubmit() {
    try {
      await pairAgent.mutateAsync({ agentId: agent.id, platform, code });
      onClose();
    } catch {
      // error displayed via pairAgent.error
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0"
        style={{ background: "rgba(20,16,10,.4)" }}
        onClick={onClose}
      />
      <div
        className="relative w-full max-w-sm rounded-2xl p-6 shadow-2xl"
        style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
      >
        <h3 className="text-[1.0625rem] font-semibold tracking-tight mb-1" style={{ color: "var(--ink)" }}>
          Pair {agent.name}
        </h3>
        <p className="text-[0.8125rem] leading-[1.5] mb-5" style={{ color: "var(--ink-3)" }}>
          Send {agent.name} a message on Slack — they&apos;ll reply with a pairing code. Enter it below to link your account.
        </p>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>Platform</label>
            <select
              className="af-input"
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
            >
              <option value="slack">Slack</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>Pairing code</label>
            <input
              className="af-input font-mono"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="Enter the code from your Slack DM"
              autoComplete="off"
            />
            <span className="text-xs" style={{ color: "var(--ink-4)" }}>
              Sent by {agent.name} in your first Slack DM
            </span>
          </div>
        </div>

        {pairAgent.error && (
          <p className="text-sm mt-3" style={{ color: "var(--err)" }}>
            {pairAgent.error instanceof Error ? pairAgent.error.message : "Pairing failed."}
          </p>
        )}

        <div className="flex gap-2 justify-end mt-5">
          <button className="af-btn af-btn-ghost" onClick={onClose}>Cancel</button>
          <button
            className="af-btn af-btn-primary"
            disabled={!code.trim() || pairAgent.isPending}
            onClick={() => { void handleSubmit(); }}
          >
            {pairAgent.isPending ? "Pairing…" : "Connect"}
          </button>
        </div>
      </div>
    </div>
  );
}
