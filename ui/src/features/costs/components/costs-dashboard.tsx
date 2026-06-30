"use client";

import React from "react";

import { useCostSummary } from "../hooks/use-cost-summary";
import { AppErrorState } from "@/components/app-error-state";
import { CostsChart } from "./costs-chart";

export function CostsDashboard() {
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

  const toggleAgent = (id: string) => {
    setExpandedAgents((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  // Pad the time series so every single day has an entry. This ensures
  // the BarChart correctly shows empty gaps for days with no spend.
  // Must be before early returns to satisfy Rules of Hooks.
  const paddedTimeSeries = React.useMemo(() => {
    const series = summary?.timeSeries ?? [];
    if (series.length === 0) return series;

    const firstDataDate = series[0]?.date ?? "";
    const lastDataDate = series[series.length - 1]?.date ?? "";

    const startD = datesValid && appliedStartDate < firstDataDate ? appliedStartDate : firstDataDate;
    const endD = datesValid && appliedEndDate > lastDataDate ? appliedEndDate : lastDataDate;

    const costMap = new Map(series.map((p) => [p.date, p.cost]));
    const padded: { date: string; cost: number }[] = [];

    let current = new Date(startD + "T00:00:00Z");
    const end = new Date(endD + "T00:00:00Z");
    let maxDays = 365 * 5; // Safety limit

    while (current <= end && maxDays-- > 0) {
      const dateStr = current.toISOString().split("T")[0];
      padded.push({ date: dateStr, cost: costMap.get(dateStr) ?? 0 });
      current.setUTCDate(current.getUTCDate() + 1);
    }

    return padded;
  }, [summary?.timeSeries, appliedStartDate, appliedEndDate, datesValid]);

  if (isLoadingSummary) {
    return (
      <div className="p-10 flex flex-col items-center justify-center min-h-[400px]">
        <div className="w-8 h-8 border-4 border-indigo-500/30 border-t-indigo-500 rounded-full animate-spin mb-4" />
        <div className="text-[14px] text-gray-500 font-medium">
          Loading costs summary...
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

  const sortedByModel = [...summary.byModel].sort(
    (a, b) => b.totalCost - a.totalCost
  );
  const maxModelCost = sortedByModel[0]?.totalCost ?? 0;

  return (
    <div className="p-10 max-w-6xl mx-auto flex flex-col gap-8">
      <header>
        <h1 className="text-[28px] font-semibold tracking-tight text-gray-900 mb-2">
          Usage &amp; Billing
        </h1>
        <p className="text-[14px] text-gray-500">
          Track API usage and token costs across all your agents.
        </p>
      </header>

      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div
          className="rounded-2xl p-6 relative overflow-hidden"
          style={{
            background: "linear-gradient(145deg, #1e1b4b, #312e81)",
            boxShadow: "0 10px 40px -10px rgba(49, 46, 129, 0.5)",
          }}
        >
          <div className="absolute top-0 right-0 -mr-10 -mt-10 w-40 h-40 rounded-full bg-white opacity-5 blur-2xl" />
          <div className="text-[13px] font-medium text-indigo-200 mb-1 tracking-wide uppercase">
            Total Spend
          </div>
          <div className="text-[36px] font-bold text-white tracking-tight flex items-baseline gap-1">
            <span className="text-[24px] text-indigo-300">$</span>
            {summary.totalCost.toFixed(4)}
          </div>
        </div>

        <div className="rounded-2xl p-6 bg-white border border-gray-200/60 shadow-sm">
          <div className="text-[13px] font-medium text-gray-500 mb-1 tracking-wide uppercase">
            Active Agents
          </div>
          <div className="text-[32px] font-bold text-gray-900 tracking-tight">
            {summary.agents.filter((a) => a.status !== "deleted").length}
          </div>
        </div>

        <div className="rounded-2xl p-6 bg-white border border-gray-200/60 shadow-sm">
          <div className="text-[13px] font-medium text-gray-500 mb-1 tracking-wide uppercase">
            Most Used Model
          </div>
          <div
            className="text-[24px] font-bold text-gray-900 tracking-tight leading-tight mt-1 truncate"
            title={sortedByModel[0]?.model ?? "None"}
          >
            {sortedByModel[0]?.model.split("/").pop() ?? "None"}
          </div>
        </div>
      </div>

      {/* Cost Over Time Chart */}
      {summary.timeSeries.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200/60 shadow-sm overflow-hidden">
          <div className="px-6 py-5 border-b border-gray-100 bg-gray-50/50 flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-[16px] font-semibold text-gray-900">
                Cost Over Time
              </h2>
              <p className="text-[13px] text-gray-400 mt-0.5">
                Daily spend across all agents
                {appliedStartDate && appliedEndDate
                  ? ` — ${appliedStartDate} to ${appliedEndDate}`
                  : " — all time"}
              </p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <label className="text-[12px] text-gray-500 font-medium">From</label>
              <input
                type="date"
                value={draftStartDate}
                max={draftEndDate || today}
                onChange={(e) => setDraftStartDate(e.target.value)}
                className="text-[13px] border border-gray-200 rounded-lg px-3 py-1.5 text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent"
              />
              <label className="text-[12px] text-gray-500 font-medium">To</label>
              <input
                type="date"
                value={draftEndDate}
                min={draftStartDate || undefined}
                max={today}
                onChange={(e) => setDraftEndDate(e.target.value)}
                className="text-[13px] border border-gray-200 rounded-lg px-3 py-1.5 text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent"
              />
              <button
                onClick={() => {
                  setAppliedStartDate(draftStartDate);
                  setAppliedEndDate(draftEndDate);
                }}
                disabled={!draftStartDate || !draftEndDate}
                className="text-[12px] bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:bg-gray-50 disabled:text-gray-400 disabled:border-gray-200 px-3 py-1.5 rounded-lg font-medium border border-indigo-200 transition-colors"
              >
                OK
              </button>
              {(appliedStartDate || draftStartDate) && (
                <button
                  onClick={() => {
                    setDraftStartDate("");
                    setDraftEndDate(today);
                    setAppliedStartDate("");
                    setAppliedEndDate(today);
                  }}
                  className="text-[12px] text-indigo-500 hover:text-indigo-700 underline"
                >
                  Reset
                </button>
              )}
            </div>
          </div>
          <div className="px-4 pt-6 pb-4">
            <CostsChart timeSeries={paddedTimeSeries} />
          </div>
        </div>
      )}

      {/* Cost by Model */}
      {sortedByModel.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200/60 shadow-sm overflow-hidden">
          <div className="px-6 py-5 border-b border-gray-100 bg-gray-50/50">
            <h2 className="text-[16px] font-semibold text-gray-900">
              Cost by Model
            </h2>
            <p className="text-[13px] text-gray-400 mt-0.5">
              Total spend grouped by AI model
            </p>
          </div>
          <div className="px-6 py-5 flex flex-col gap-4">
            {sortedByModel.map((entry) => {
              const pct = maxModelCost > 0 ? (entry.totalCost / maxModelCost) * 100 : 0;
              const shortName = entry.model.split("/").pop() ?? entry.model;
              return (
                <div key={entry.model} className="flex items-center gap-4">
                  <div
                    className="text-[13px] font-medium text-gray-700 shrink-0"
                    style={{ width: 160 }}
                    title={entry.model}
                  >
                    {shortName}
                  </div>
                  <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-2 rounded-full bg-indigo-500 transition-all duration-500"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="text-[13px] font-semibold text-gray-900 shrink-0 font-mono w-24 text-right">
                    ${entry.totalCost.toFixed(5)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Agents Cost Breakdown */}
      <div className="bg-white rounded-2xl border border-gray-200/60 shadow-sm overflow-hidden">
        <div className="px-6 py-5 border-b border-gray-100 bg-gray-50/50">
          <h2 className="text-[16px] font-semibold text-gray-900">
            Agent Breakdown
          </h2>
        </div>

        {summary.agents.length === 0 ? (
          <div className="p-10 text-center text-[14px] text-gray-500">
            No agent cost data found.
          </div>
        ) : (
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="px-6 py-3 text-[12px] font-medium text-gray-500 uppercase tracking-wider">
                  Agent
                </th>
                <th className="px-6 py-3 text-[12px] font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-[12px] font-medium text-gray-500 uppercase tracking-wider">
                  Model
                </th>
                <th className="px-6 py-3 text-[12px] font-medium text-gray-500 uppercase tracking-wider text-right">
                  Input Tokens
                </th>
                <th className="px-6 py-3 text-[12px] font-medium text-gray-500 uppercase tracking-wider text-right">
                  Output Tokens
                </th>
                <th className="px-6 py-3 text-[12px] font-medium text-gray-500 uppercase tracking-wider text-right">
                  Cost
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {summary.agents.map((agent) => {
                // Fallback for deleted/older agents
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

                // NEW: Calculate the true totals from the breakdown array
                // If the top-level agent stats are missing/0, this pulls the real numbers from the sub-models
                const displayPromptTokens = Math.max(
                  agent.promptTokens,
                  effectiveBreakdown.reduce((sum, m) => sum + m.promptTokens, 0)
                );
                const displayCompletionTokens = Math.max(
                  agent.completionTokens,
                  effectiveBreakdown.reduce((sum, m) => sum + m.completionTokens, 0)
                );

                return (
                  <React.Fragment key={agent.agentId}>
                    {/* Main agent row */}
                    <tr
                      className="hover:bg-gray-50/50 transition-colors cursor-pointer"
                      onClick={() => effectiveBreakdown.length > 0 && toggleAgent(agent.agentId)}
                    >
                      <td className="px-6 py-4">
                        <div className="text-[14px] font-medium text-gray-900">
                          {agent.agentName}
                        </div>
                        <div className="text-[12px] text-gray-400 font-mono mt-0.5">
                          {agent.agentId.split("-")[0]}...
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <div
                          className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium uppercase tracking-wider
                            ${agent.status === "active" ? "bg-green-50 text-green-700 border border-green-200" : ""}
                            ${agent.status === "stopped" ? "bg-yellow-50 text-yellow-700 border border-yellow-200" : ""}
                            ${agent.status === "deleted" ? "bg-red-50 text-red-700 border border-red-200" : ""}
                            ${agent.status === "error" ? "bg-orange-50 text-orange-700 border border-orange-200" : ""}
                            ${agent.status === "unknown" ? "bg-gray-50 text-gray-700 border border-gray-200" : ""}
                          `}
                        >
                          {agent.status}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500">
                        {effectiveBreakdown.length > 0 ? (
                          <span className="flex items-center gap-1">
                            {expandedAgents.has(agent.agentId) ? "▾" : "▸"}
                            {effectiveBreakdown.length} model(s)
                          </span>
                        ) : agent.model ? (
                          <span className="inline-flex px-2 py-0.5 rounded bg-gray-50 text-gray-700 text-[11px] border border-gray-200">
                            {agent.model.split("/").pop()}
                          </span>
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>

                      {/* UPDATED: Using the calculated display tokens */}
                      <td className="px-6 py-4 text-right text-[13px] font-mono">
                        {displayPromptTokens.toLocaleString()}
                      </td>
                      <td className="px-6 py-4 text-right text-[13px] font-mono">
                        {displayCompletionTokens.toLocaleString()}
                      </td>

                      <td className="px-6 py-4 text-right font-semibold">
                        ${agent.totalCost.toFixed(5)}
                      </td>
                    </tr>

                    {/* Per-model sub-rows */}
                    {expandedAgents.has(agent.agentId) &&
                      effectiveBreakdown.map((m) => (
                        <tr key={`${agent.agentId}-${m.model}`} className="bg-gray-50/30">
                          <td className="px-6 py-2 pl-12 text-[12px] text-gray-400">
                            ↳ {m.model.split("/").pop()}
                          </td>
                          <td />
                          <td className="px-6 py-2">
                            <span className="inline-flex px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 text-[11px] border border-indigo-100">
                              {m.model.split("/").pop()}
                            </span>
                          </td>
                          <td className="px-6 py-2 text-right text-[12px] font-mono text-gray-500">
                            {m.promptTokens.toLocaleString()}
                          </td>
                          <td className="px-6 py-2 text-right text-[12px] font-mono text-gray-500">
                            {m.completionTokens.toLocaleString()}
                          </td>
                          <td className="px-6 py-2 text-right text-[12px] font-mono text-gray-600">
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
      </div>
    </div>
  );
}
