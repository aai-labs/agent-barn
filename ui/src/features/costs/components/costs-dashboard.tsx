"use client";

import React from "react";

import { useCostSummary } from "../hooks/use-cost-summary";
import { AppErrorState } from "@/components/app-error-state";
import { useRequireOrgManager } from "@/features/organizations/hooks/use-require-org-manager";
import { CostsChart } from "./costs-chart";

export function CostsDashboard() {
  // Costs are owner/admin-only; redirect a member here (e.g. via org switch) to org home.
  const canManage = useRequireOrgManager();
  const today = new Date().toISOString().split("T")[0];
  const [appliedStartDate, setAppliedStartDate] = React.useState<string>("");
  const [appliedEndDate, setAppliedEndDate] = React.useState<string>(today);

  const [draftStartDate, setDraftStartDate] = React.useState<string>("");
  const [draftEndDate, setDraftEndDate] = React.useState<string>(today);

  const isValidDate = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s);
  const datesValid = isValidDate(appliedStartDate) && isValidDate(appliedEndDate);

  const { summary, isLoadingSummary, error, refetch } = useCostSummary(
    datesValid ? { startDate: appliedStartDate, endDate: appliedEndDate } : {}
  );

  const [expandedAgents, setExpandedAgents] = React.useState<Set<string>>(new Set());
  const [currentPage, setCurrentPage] = React.useState(1);
  const PAGE_SIZE = 10;

  const [currentModelPage, setCurrentModelPage] = React.useState(1);
  const MODEL_PAGE_SIZE = 12;

  const toggleAgent = (id: string) => {
    setExpandedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // Pad the time series so every single day has an entry.
  const paddedTimeSeries = React.useMemo(() => {
    const series = summary?.timeSeries ?? [];
    if (series.length === 0) return series;

    const firstDataDate = series[0]?.date ?? "";
    const lastDataDate = series[series.length - 1]?.date ?? "";

    const startD = datesValid && appliedStartDate < firstDataDate ? appliedStartDate : firstDataDate;
    const endD = datesValid && appliedEndDate > lastDataDate ? appliedEndDate : lastDataDate;

    const costMap = new Map(series.map((p) => [p.date, p.cost]));
    const padded: { date: string; cost: number }[] = [];

    const current = new Date(startD + "T00:00:00Z");
    const end = new Date(endD + "T00:00:00Z");
    let maxDays = 365 * 5;

    while (current <= end && maxDays-- > 0) {
      const dateStr = current.toISOString().split("T")[0];
      padded.push({ date: dateStr, cost: costMap.get(dateStr) ?? 0 });
      current.setUTCDate(current.getUTCDate() + 1);
    }

    return padded;
  }, [summary?.timeSeries, appliedStartDate, appliedEndDate, datesValid]);

  // Redirecting (member on an owner/admin page) — render nothing meanwhile.
  if (!canManage) {
    return null;
  }

  if (isLoadingSummary) {
    return (
      <div className="max-w-[75rem] mx-auto px-10 pt-9 pb-24 flex flex-col items-center justify-center min-h-[400px]">
        <div
          className="w-7 h-7 rounded-full border-2 border-t-transparent animate-spin mb-4"
          style={{ borderColor: "var(--line-strong)", borderTopColor: "transparent" }}
        />
        <div className="text-[0.875rem]" style={{ color: "var(--ink-3)" }}>
          Loading costs…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <AppErrorState
        error={error}
        title="Unable to load cost summary"
        description="We couldn't fetch the latest cost data right now."
        onRetry={() => void refetch()}
        retryLabel="Retry"
      />
    );
  }

  if (!summary) {
    return null;
  }

  // Deduplicate by short display name — LiteLLM can report the same model
  // under different full paths (e.g. "qwen/qwen3-6-plus" vs
  // "openrouter/qwen/qwen3-6-plus"). We merge them by their last segment.
  const modelMap = new Map<string, number>();
  for (const entry of summary.byModel) {
    const shortName = entry.model.split("/").pop() ?? entry.model;
    modelMap.set(shortName, (modelMap.get(shortName) ?? 0) + entry.totalCost);
  }
  const sortedByModel = [...modelMap.entries()]
    .map(([model, totalCost]) => ({ model, totalCost }))
    .sort((a, b) => b.totalCost - a.totalCost);
  const maxModelCost = sortedByModel[0]?.totalCost ?? 0;


  return (
    <div className="max-w-[75rem] mx-auto px-10 pt-9 pb-24">
      {/* Page header */}
      <div className="mb-14">
        <h1
          className="text-4xl font-medium tracking-[-0.028em] leading-[1.18] m-0 mb-3"
          style={{ color: "var(--ink)" }}
        >
          Usage &amp; Billing
        </h1>
        <div className="text-[0.906rem]" style={{ color: "var(--ink-3)" }}>
          Track API usage and token costs across all your agents.
        </div>
      </div>

      {/* Overview stat cards */}
      <div className="mb-12">
        <div
          className="grid gap-4"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(22rem, 1fr))" }}
        >
          <div className="af-card px-5.5 py-5 flex flex-col gap-1">
            <div className="text-[0.813rem] font-medium uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>
              Total Spend
            </div>
            <div className="text-[2rem] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
              <span className="text-[1.25rem]" style={{ color: "var(--ink-4)" }}>$</span>
              {summary.totalCost.toFixed(4)}
            </div>
          </div>

          <div className="af-card px-5.5 py-5 flex flex-col gap-1">
            <div className="text-[0.813rem] font-medium uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>
              Active Agents
            </div>
            <div className="text-[2rem] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
              {summary.agents.filter((a) => a.status !== "deleted").length}
            </div>
          </div>

          <div className="af-card px-5.5 py-5 flex flex-col gap-1">
            <div className="text-[0.813rem] font-medium uppercase tracking-wide" style={{ color: "var(--ink-4)" }}>
              Top Model
            </div>
            <div
              className="text-[1.375rem] font-semibold tracking-tight leading-tight mt-1 truncate"
              style={{ color: "var(--ink)" }}
              title={sortedByModel[0]?.model ?? "None"}
            >
              {sortedByModel[0]?.model.split("/").pop() ?? "None"}
            </div>
          </div>
        </div>
      </div>


      {/* Cost Over Time */}
      {summary.timeSeries.length > 0 && (
        <div className="mb-12">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
                Cost over time
              </h2>
              <div className="text-[0.844rem] mt-0.5" style={{ color: "var(--ink-3)" }}>
                Daily spend across all agents
                {appliedStartDate && appliedEndDate
                  ? ` — ${appliedStartDate} to ${appliedEndDate}`
                  : " — all time"}
              </div>
            </div>
            {/* Date filter */}
            <div className="flex items-center gap-2 flex-wrap">
              <label className="text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>From</label>
              <input
                type="date"
                value={draftStartDate}
                max={draftEndDate || today}
                onChange={(e) => setDraftStartDate(e.target.value)}
                className="text-[0.8125rem] rounded-lg px-3 py-1.5 focus:outline-none"
                style={{
                  border: "1px solid var(--line-strong)",
                  background: "var(--bg-elev)",
                  color: "var(--ink-2)",
                }}
              />
              <label className="text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>To</label>
              <input
                type="date"
                value={draftEndDate}
                min={draftStartDate || undefined}
                max={today}
                onChange={(e) => setDraftEndDate(e.target.value)}
                className="text-[0.8125rem] rounded-lg px-3 py-1.5 focus:outline-none"
                style={{
                  border: "1px solid var(--line-strong)",
                  background: "var(--bg-elev)",
                  color: "var(--ink-2)",
                }}
              />
              <button
                className="af-btn"
                onClick={() => {
                  setAppliedStartDate(draftStartDate);
                  setAppliedEndDate(draftEndDate);
                  setCurrentPage(1);
                  setCurrentModelPage(1);
                }}
                disabled={!draftStartDate || !draftEndDate}
              >
                Apply
              </button>
              {(appliedStartDate || draftStartDate) && (
                <button
                  className="af-btn af-btn-ghost"
                  onClick={() => {
                    setDraftStartDate("");
                    setDraftEndDate(today);
                    setAppliedStartDate("");
                    setAppliedEndDate(today);
                    setCurrentPage(1);
                    setCurrentModelPage(1);
                  }}
                >
                  Reset
                </button>
              )}
            </div>
          </div>

          <div className="af-card px-4 pt-6 pb-4">
            <CostsChart timeSeries={paddedTimeSeries} />
          </div>
        </div>
      )}

      {/* Cost by Model */}
      {sortedByModel.length > 0 && (
        <div className="mb-12">
          <div className="mb-5">
            <h2 className="text-lg font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
              Cost by model
            </h2>
            <div className="text-[0.844rem] mt-0.5" style={{ color: "var(--ink-3)" }}>
              Total spend grouped by AI model
            </div>
          </div>

          <div className="af-card flex flex-col gap-4 overflow-hidden">
            <div className="px-5.5 pt-5 pb-5 flex flex-col gap-4">
              {sortedByModel.slice((currentModelPage - 1) * MODEL_PAGE_SIZE, currentModelPage * MODEL_PAGE_SIZE).map((entry) => {
                const pct = maxModelCost > 0 ? (entry.totalCost / maxModelCost) * 100 : 0;
                return (
                  <div key={entry.model} className="flex items-center gap-4">
                    <div
                      className="text-[0.8125rem] font-medium shrink-0"
                      style={{ width: 160, color: "var(--ink-2)" }}
                      title={entry.model}
                    >
                      {entry.model}
                    </div>
                    <div
                      className="flex-1 h-1.5 rounded-full overflow-hidden"
                      style={{ background: "var(--bg-sunken)" }}
                    >
                      <div
                        className="h-1.5 rounded-full transition-all duration-500"
                        style={{ width: `${pct}%`, background: "var(--ink-3)" }}
                      />
                    </div>
                    <div
                      className="text-[0.8125rem] font-semibold shrink-0 font-mono w-24 text-right"
                      style={{ color: "var(--ink)" }}
                    >
                      ${entry.totalCost.toFixed(5)}
                    </div>
                  </div>
                );
              })}
            </div>

            {sortedByModel.length > MODEL_PAGE_SIZE && (
              <div
                className="px-5.5 py-4 flex items-center justify-between"
                style={{ borderTop: "1px solid var(--line)" }}
              >
                <div className="text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>
                  Showing {(currentModelPage - 1) * MODEL_PAGE_SIZE + 1}–{Math.min(currentModelPage * MODEL_PAGE_SIZE, sortedByModel.length)} of {sortedByModel.length} models
                </div>
                <div className="flex gap-2">
                  <button
                    className="af-btn af-btn-ghost text-[0.8125rem]"
                    onClick={() => setCurrentModelPage((p) => Math.max(1, p - 1))}
                    disabled={currentModelPage === 1}
                  >
                    Previous
                  </button>
                  <button
                    className="af-btn af-btn-ghost text-[0.8125rem]"
                    onClick={() =>
                      setCurrentModelPage((p) =>
                        Math.min(Math.ceil(sortedByModel.length / MODEL_PAGE_SIZE), p + 1)
                      )
                    }
                    disabled={currentModelPage >= Math.ceil(sortedByModel.length / MODEL_PAGE_SIZE)}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Agent Breakdown table */}
      <div>
        <div className="mb-5">
          <h2 className="text-lg font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
            Agent breakdown
          </h2>
        </div>

        <div className="af-card overflow-hidden">
          {summary.agents.length === 0 ? (
            <div className="p-10 text-center text-[0.875rem]" style={{ color: "var(--ink-3)" }}>
              No agent cost data found.
            </div>
          ) : (
            <table className="w-full text-left border-collapse">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--line)" }}>
                  {["Agent", "Status", "Model", "Input Tokens", "Output Tokens", "Cost"].map((h, i) => (
                    <th
                      key={h}
                      className={`px-6 py-3 text-[0.75rem] font-medium uppercase tracking-wider${i >= 3 ? " text-right" : ""}`}
                      style={{ color: "var(--ink-4)" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {summary.agents.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE).map((agent) => {
                  const effectiveBreakdown = agent.modelsBreakdown?.length > 0
                    ? agent.modelsBreakdown
                    : agent.model
                      ? [
                        {
                          model: agent.model,
                          totalCost: agent.totalCost,
                          promptTokens: agent.promptTokens,
                          completionTokens: agent.completionTokens,
                        },
                      ]
                      : [];

                  const displayPromptTokens = Math.max(
                    agent.promptTokens,
                    effectiveBreakdown.reduce((sum, m) => sum + m.promptTokens, 0)
                  );
                  const displayCompletionTokens = Math.max(
                    agent.completionTokens,
                    effectiveBreakdown.reduce((sum, m) => sum + m.completionTokens, 0)
                  );

                  const statusColor: Record<string, string> = {
                    active: "#15803d",
                    stopped: "var(--ink-3)",
                    deleted: "#b42318",
                    error: "#c2410c",
                    unknown: "var(--ink-4)",
                  };
                  const sc = statusColor[agent.status] ?? statusColor.unknown;

                  return (
                    <React.Fragment key={agent.agentId}>
                      <tr
                        className="transition-colors cursor-pointer"
                        style={{ borderBottom: "1px solid var(--line)" }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-soft)")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                        onClick={() => effectiveBreakdown.length > 0 && toggleAgent(agent.agentId)}
                      >
                        <td className="px-6 py-4">
                          <div className="text-[0.875rem] font-medium" style={{ color: "var(--ink)" }}>
                            {agent.agentName}
                          </div>
                          <div className="text-[0.75rem] font-mono mt-0.5" style={{ color: "var(--ink-4)" }}>
                            {agent.agentId.split("-")[0]}…
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <span
                            className="text-[0.8125rem] font-medium capitalize"
                            style={{ color: sc }}
                          >
                            {agent.status}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>
                          {effectiveBreakdown.length > 0 ? (
                            <span className="flex items-center gap-1">
                              {expandedAgents.has(agent.agentId) ? "▾" : "▸"}
                              {effectiveBreakdown.length} model(s)
                            </span>
                          ) : agent.model ? (
                            <span
                              className="inline-flex px-2 py-0.5 rounded text-[0.6875rem]"
                              style={{ background: "var(--bg-soft)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
                            >
                              {agent.model.split("/").pop()}
                            </span>
                          ) : (
                            <span style={{ color: "var(--ink-5)" }}>—</span>
                          )}
                        </td>
                        <td className="px-6 py-4 text-right text-[0.8125rem] font-mono" style={{ color: "var(--ink-2)" }}>
                          {displayPromptTokens.toLocaleString()}
                        </td>
                        <td className="px-6 py-4 text-right text-[0.8125rem] font-mono" style={{ color: "var(--ink-2)" }}>
                          {displayCompletionTokens.toLocaleString()}
                        </td>
                        <td className="px-6 py-4 text-right font-semibold text-[0.875rem]" style={{ color: "var(--ink)" }}>
                          ${agent.totalCost.toFixed(5)}
                        </td>
                      </tr>

                      {expandedAgents.has(agent.agentId) &&
                        effectiveBreakdown.map((m) => (
                          <tr
                            key={`${agent.agentId}-${m.model}`}
                            style={{ background: "var(--bg-elev)", borderBottom: "1px solid var(--line)" }}
                          >
                            <td className="px-6 py-2 pl-12 text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
                            </td>
                            <td />
                            <td className="px-6 py-2">
                              <span
                                className="inline-flex px-2 py-0.5 rounded text-[0.6875rem]"
                                style={{ background: "var(--bg-sunken)", color: "var(--ink-3)", border: "1px solid var(--line)" }}
                              >
                                {m.model.split("/").pop()}
                              </span>
                            </td>
                            <td className="px-6 py-2 text-right text-[0.75rem] font-mono" style={{ color: "var(--ink-3)" }}>
                              {m.promptTokens.toLocaleString()}
                            </td>
                            <td className="px-6 py-2 text-right text-[0.75rem] font-mono" style={{ color: "var(--ink-3)" }}>
                              {m.completionTokens.toLocaleString()}
                            </td>
                            <td className="px-6 py-2 text-right text-[0.75rem] font-mono" style={{ color: "var(--ink-2)" }}>
                              ${m.totalCost.toFixed(5)}
                            </td>
                          </tr>
                        ))}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          )}

          {/* Pagination controls */}
          {summary.agents.length > PAGE_SIZE && (
            <div
              className="px-6 py-4 flex items-center justify-between"
              style={{ borderTop: "1px solid var(--line)" }}
            >
              <div className="text-[0.8125rem]" style={{ color: "var(--ink-3)" }}>
                Showing {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, summary.agents.length)} of {summary.agents.length} agents
              </div>
              <div className="flex gap-2">
                <button
                  className="af-btn af-btn-ghost text-[0.8125rem]"
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                >
                  Previous
                </button>
                <button
                  className="af-btn af-btn-ghost text-[0.8125rem]"
                  onClick={() =>
                    setCurrentPage((p) =>
                      Math.min(Math.ceil(summary.agents.length / PAGE_SIZE), p + 1)
                    )
                  }
                  disabled={currentPage >= Math.ceil(summary.agents.length / PAGE_SIZE)}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
