/* eslint-disable @typescript-eslint/no-unused-vars */
import type { Agent } from "../schemas";

interface WorkTabProps {
  agent: Agent;
}

const workItems = [
  { t: "9:14 AM", what: "Posted standup recap", where: "#eng-platform", icon: "slack" },
  { t: "9:08 AM", what: "Pinged Raj & Tomas about standup", where: "DM", icon: "slack" },
  { t: "8:42 AM", what: "Closed JIRA PROJ-902", where: "jira", icon: "jira" },
  { t: "Yesterday", what: "Drafted sprint recap", where: "#eng-platform", icon: "slack" },
  { t: "Yesterday", what: "Reviewed 14 standup posts", where: "#eng-standups", icon: "slack" },
  { t: "May 10", what: "Created sprint goals doc", where: "Confluence", icon: "book" },
  { t: "May 9", what: "Helped Sara reschedule a 1:1", where: "Google Cal", icon: "calendar" },
];

export function WorkTab({ agent: _ }: WorkTabProps) {
  return <ComingSoon />;
}

function StatBox({ label, primary, sub }: { label: string; primary: string; sub: string }) {
  return (
    <div className="af-card px-5 py-[18px]">
      <div
        className="text-[12px] uppercase tracking-[0.08em] font-semibold mb-1.5"
        style={{ color: "var(--ink-3)" }}
      >
        {label}
      </div>
      <div className="text-[22px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
        {primary}
      </div>
      <div className="text-[13px] mt-1" style={{ color: "var(--ink-3)" }}>
        {sub}
      </div>
    </div>
  );
}

function ComingSoon() {
  return (
    <div
      className="flex flex-col items-center justify-center text-center py-20 rounded-2xl"
      style={{ border: "1px dashed var(--line-strong)" }}
    >
      <div className="text-3xl mb-3">🚧</div>
      <div className="font-medium text-[15px] mb-1" style={{ color: "var(--ink)" }}>Coming soon</div>
      <div className="text-[13.5px]" style={{ color: "var(--ink-3)" }}>
        Activity and spend data will appear here soon.
      </div>
    </div>
  );
}

function WorkIcon({ icon }: { icon: string }) {
  const cls = "w-3.5 h-3.5";
  if (icon === "slack") return (
    <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 10V5a2 2 0 1 1 4 0v5h-4z"/><path d="M14 14h5a2 2 0 1 1 0 4h-5v-4z"/><path d="M10 14v5a2 2 0 1 1-4 0v-5h4z"/><path d="M10 10H5a2 2 0 1 1 0-4h5v4z"/>
    </svg>
  );
  if (icon === "jira") return (
    <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2 4 10l4 4 8-8z"/><path d="M12 22 4 14"/>
    </svg>
  );
  if (icon === "book") return (
    <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5z"/><path d="M8 7h8M8 11h6"/>
    </svg>
  );
  return (
    <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>
    </svg>
  );
}
