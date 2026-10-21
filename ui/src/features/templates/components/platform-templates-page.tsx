"use client";

import { TemplatesPanel } from "./templates-panel";

export function PlatformTemplatesPage() {
  return (
    <div>
      <div className="mb-8">
        <h1
          className="text-[28px] font-semibold tracking-tight m-0 mb-1"
          style={{ color: "var(--ink)" }}
        >
          Platform templates
        </h1>
        <p className="text-[14px] m-0" style={{ color: "var(--ink-3)" }}>
          Author the global agent prompts that organizations can use.
        </p>
      </div>

      <TemplatesPanel scope={{ kind: "platform" }} />
    </div>
  );
}
