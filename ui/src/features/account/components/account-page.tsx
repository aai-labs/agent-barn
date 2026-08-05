"use client";

import { ChangePasswordSection } from "./change-password-section";
import { SlackTokenSection } from "./slack-token-section";

export function AccountPage() {
  return (
    <div className="af-page">
      <h1
        className="text-[28px] font-semibold tracking-tight m-0 mb-1"
        style={{ color: "var(--ink)" }}
      >
        Account
      </h1>
      <p className="text-[15px] mt-0 mb-8" style={{ color: "var(--ink-3)" }}>
        Personal settings and credentials.
      </p>

      <div className="flex flex-col gap-6">
        <ChangePasswordSection />
        <SlackTokenSection />
      </div>
    </div>
  );
}
