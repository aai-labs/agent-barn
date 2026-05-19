import type { Agent } from "../types";
import { SKILLS, fmtCost, getTemplate } from "../data";
import { CogIcon } from "@/components/icons";

interface AboutTabProps {
  agent: Agent;
  onConfigure: () => void;
}

export function AboutTab({ agent, onConfigure }: AboutTabProps) {
  return <ComingSoon onConfigure={onConfigure} />;

  return (
    <div className="grid gap-7 items-start" style={{ gridTemplateColumns: "1fr 300px" }}>
      <div className="flex flex-col gap-8">
        <section>
          <SectionLabel>What they can do</SectionLabel>
          <div className="grid grid-cols-2 gap-2.5">
            {agent.skills.map((s) => {
              const skill = SKILLS.find((x) => x.id === s);
              return (
                <div
                  key={s}
                  className="px-3.5 py-3 rounded-xl"
                  style={{ border: "1px solid var(--line)" }}
                >
                  <div className="font-medium text-[13.5px]" style={{ color: "var(--ink)" }}>
                    {skill?.name ?? s}
                  </div>
                  <div className="text-[12.5px] mt-0.5 leading-[1.4]" style={{ color: "var(--ink-3)" }}>
                    {skill?.desc ?? ""}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>

      <aside className="af-card px-5 py-[18px]">
        {[
          ["Template", <span key="t" className="font-mono text-[12.5px]">{getTemplate(agent.template_id)?.slug ?? agent.template_id}@{agent.templateVersion}</span>],
          ["Model", <span key="m" className="font-mono text-[12.5px]">claude-sonnet-4.5</span>],
          ["Hired", <span key="h">{agent.createdAt}</span>],
          ["Spend / mo", <span key="s" className="font-mono text-[12.5px]">{fmtCost(agent.costMonth)}</span>],
        ].map(([label, value]) => (
          <div
            key={String(label)}
            className="flex items-center justify-between py-2.5 text-[13.5px]"
            style={{ borderBottom: "1px solid var(--line)" }}
          >
            <span style={{ color: "var(--ink-4)" }}>{label}</span>
            <span style={{ color: "var(--ink)" }}>{value}</span>
          </div>
        ))}
        <button
          className="af-btn w-full justify-center mt-4"
          onClick={onConfigure}
        >
          <CogIcon /> Open configuration
        </button>
        <div className="text-[12px] mt-2.5 leading-[1.5]" style={{ color: "var(--ink-4)" }}>
          Configuration covers personality, behaviors, allowed channels, k8s resources and vaulted keys.
        </div>
      </aside>
    </div>
  );
}

function ComingSoon({ onConfigure }: { onConfigure: () => void }) {
  return (
    <div
      className="flex flex-col items-center justify-center text-center py-20 rounded-2xl"
      style={{ border: "1px dashed var(--line-strong)" }}
    >
      <div className="text-3xl mb-3">🚧</div>
      <div className="font-medium text-[15px] mb-1" style={{ color: "var(--ink)" }}>Coming soon</div>
      <div className="text-[13.5px] mb-5" style={{ color: "var(--ink-3)" }}>
        Skills, template metadata, and cost breakdown will appear here soon.
      </div>
      <button className="af-btn af-btn-sm" onClick={onConfigure}>
        Open configuration →
      </button>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-[12px] uppercase tracking-[0.08em] font-semibold mb-2.5"
      style={{ color: "var(--ink-3)" }}
    >
      {children}
    </div>
  );
}

