"use client";

import { SlackTokenSection } from "./slack-token-section";

export function AccountPage() {
  return (
    <div className="max-w-[720px] mx-auto px-10 pt-9 pb-24">
      <h1
        className="text-[28px] font-semibold tracking-tight m-0 mb-1"
        style={{ color: "var(--ink)" }}
      >
        Account
      </h1>
      <p className="text-[15px] mt-0 mb-8" style={{ color: "var(--ink-3)" }}>
        Personal settings and credentials.
      </p>

      <SlackTokenSection />
    </div>
  );
}
