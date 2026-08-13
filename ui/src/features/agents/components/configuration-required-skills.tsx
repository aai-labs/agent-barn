import type { Snapshot } from "./agent-configuration-utils";

export function ConfigurationRequiredSkills({
  snapshot,
}: {
  snapshot: Snapshot;
}) {
  return (
    <div className="mt-5">
      <div
        className="mb-2 text-[0.75rem] font-semibold uppercase tracking-[0.08em]"
        style={{ color: "var(--ink-4)" }}
      >
        Required skills
      </div>
      {snapshot.requiredSkills.length === 0 ? (
        <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          No required skills on this configuration.
        </p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {snapshot.requiredSkills.map((skill) => (
            <span
              key={skill.id}
              className="rounded-full border px-2.5 py-1 text-[0.78rem]"
              style={{ borderColor: "var(--line)", color: "var(--ink-2)" }}
              title={
                skill.requiredProviders.length
                  ? `Providers: ${skill.requiredProviders.join(", ")}`
                  : undefined
              }
            >
              {skill.name}
              {skill.groupKey ? ` · one of ${skill.groupKey}` : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
