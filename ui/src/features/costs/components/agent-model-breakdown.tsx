"use client";

import {
  formatCallSpend,
  formatModelLabel,
  formatPercent,
  formatSpend,
  formatTokens,
} from "../format";
import type { AgentModelBreakdown as ModelBreakdownRow } from "../schemas";

const TH = "py-2 px-2 font-medium first:pl-0 last:pr-0";
const TD = "py-2 px-2 tabular-nums first:pl-0 last:pr-0";

/** Where one Agent's spend went, by model, biggest first as the server ranks it. */
export function AgentModelBreakdown({
  models,
  totalCost,
}: {
  models: ModelBreakdownRow[];
  totalCost: number;
}) {
  const headerStyle = {
    borderBottom: "1px solid var(--line)",
    color: "var(--ink-3)",
  };

  return (
    <div className="af-card p-4 mb-6" data-testid="agent-cost-by-model">
      <h2
        className="m-0 mb-3 text-[14px] font-semibold"
        style={{ color: "var(--ink)" }}
      >
        Spend by model
      </h2>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr>
              <th scope="col" className={`${TH} text-left`} style={headerStyle}>
                Model
              </th>
              <th scope="col" className={`${TH} text-left w-[22%]`} style={headerStyle}>
                Share
              </th>
              <th scope="col" className={`${TH} text-right`} style={headerStyle}>
                Spend
              </th>
              <th scope="col" className={`${TH} text-right`} style={headerStyle}>
                Calls
              </th>
              <th scope="col" className={`${TH} text-right`} style={headerStyle}>
                Per call
              </th>
              <th scope="col" className={`${TH} text-right`} style={headerStyle}>
                Prompt
              </th>
              <th scope="col" className={`${TH} text-right`} style={headerStyle}>
                Completion
              </th>
            </tr>
          </thead>
          <tbody>
            {models.map((entry) => {
              const share = totalCost > 0 ? entry.totalCost / totalCost : 0;
              return (
                <tr key={entry.model}>
                  <td
                    className={`${TD} max-w-[1px] truncate text-left`}
                    style={{ color: "var(--ink-2)" }}
                    title={entry.model}
                  >
                    {formatModelLabel(entry.model)}
                  </td>
                  <td className={TD}>
                    <div className="flex items-center gap-2">
                      <div
                        className="h-1.5 flex-1 overflow-hidden rounded-full"
                        style={{ background: "var(--bg-soft)" }}
                        aria-hidden
                      >
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.round(share * 100)}%`,
                            background: "var(--ink-3)",
                          }}
                        />
                      </div>
                      <span
                        className="w-9 text-right text-[12px]"
                        style={{ color: "var(--ink-3)" }}
                      >
                        {formatPercent(share)}
                      </span>
                    </div>
                  </td>
                  <td className={`${TD} text-right`} style={{ color: "var(--ink)" }}>
                    {formatSpend(entry.totalCost)}
                  </td>
                  <td className={`${TD} text-right`} style={{ color: "var(--ink-3)" }}>
                    {entry.calls.toLocaleString()}
                  </td>
                  <td className={`${TD} text-right`} style={{ color: "var(--ink-3)" }}>
                    {entry.calls > 0
                      ? formatCallSpend(entry.totalCost / entry.calls)
                      : "—"}
                  </td>
                  <td className={`${TD} text-right`} style={{ color: "var(--ink-3)" }}>
                    {formatTokens(entry.promptTokens)}
                  </td>
                  <td className={`${TD} text-right`} style={{ color: "var(--ink-3)" }}>
                    {formatTokens(entry.completionTokens)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
