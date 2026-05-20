import type { Agent } from "../schemas";

interface AboutTabProps {
  agent: Agent;
  onConfigure: () => void;
}

export function AboutTab({ onConfigure }: AboutTabProps) {
  return <ComingSoon onConfigure={onConfigure} />;
}

function ComingSoon({ onConfigure }: { onConfigure: () => void }) {
  return (
    <div
      className="flex flex-col items-center justify-center text-center py-20 rounded-2xl"
      style={{ border: "1px dashed var(--line-strong)" }}
    >
      <div className="text-3xl mb-3">🚧</div>
      <div className="font-medium text-[0.9375rem] mb-1" style={{ color: "var(--ink)" }}>Coming soon</div>
      <div className="text-[0.844rem] mb-5" style={{ color: "var(--ink-3)" }}>
        Skills, template metadata, and cost breakdown will appear here soon.
      </div>
      <button className="af-btn af-btn-sm" onClick={onConfigure}>
        Open configuration →
      </button>
    </div>
  );
}
