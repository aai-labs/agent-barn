"use client";

import { TextMessagePartProvider } from "@assistant-ui/react";
import { MarkdownText } from "@/components/assistant-ui/elements/markdown-text";

/** Renders Markdown with the same viewer the chat uses. */
export function WorkflowMarkdown({ text }: { text: string }) {
  return (
    <TextMessagePartProvider text={text}>
      <MarkdownText />
    </TextMessagePartProvider>
  );
}
