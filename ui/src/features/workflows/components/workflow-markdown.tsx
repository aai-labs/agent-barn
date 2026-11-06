"use client";

import { TextMessagePartProvider } from "@assistant-ui/react";
import { MarkdownText } from "@/components/assistant-ui/elements/markdown-text";

/** Unwrap a previously stored malformed result envelope without changing ordinary text. */
function displaySummary(text: string): string {
  try {
    const value: unknown = JSON.parse(text.replace(/,\s*"\s*"criteria_met"\s*:/, ', "criteria_met":'));
    if (value && typeof value === "object" && "summary" in value && "criteria_met" in value &&
        typeof value.summary === "string" && typeof value.criteria_met === "boolean") return value.summary;
  } catch {
    // Ordinary Markdown is not JSON.
  }
  return text;
}

/** Renders Markdown with the same viewer the chat uses. */
export function WorkflowMarkdown({ text }: { text: string }) {
  return (
    <div className="min-w-0 overflow-hidden [overflow-wrap:anywhere] [&_pre]:max-w-full [&_pre]:overflow-x-auto [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto">
      <TextMessagePartProvider text={displaySummary(text)}>
        <MarkdownText />
      </TextMessagePartProvider>
    </div>
  );
}
