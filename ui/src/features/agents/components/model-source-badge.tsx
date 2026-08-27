"use client";

/**
 * Says where an Agent's model came from. Worth showing everywhere the model is
 * shown: "GLM 5.2" alone cannot tell you whether changing the organization default
 * will move this Agent.
 */
export function ModelSourceBadge({ source }: { source: "default" | "override" }) {
  const isDefault = source === "default";
  return (
    <span
      className="inline-flex items-center rounded-md px-1.5 py-0.5 text-[0.68rem] font-medium"
      style={{
        background: "var(--bg-soft)",
        border: `1px ${isDefault ? "dashed" : "solid"} var(--line-strong)`,
        color: "var(--ink-3)",
      }}
      title={
        isDefault
          ? "Follows the organization default, so it moves when the default changes."
          : "Pinned to this model, so the organization default does not affect it."
      }
    >
      {isDefault ? "default" : "custom"}
    </span>
  );
}
