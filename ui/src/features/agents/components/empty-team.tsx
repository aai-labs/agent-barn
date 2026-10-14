import { ArrowRight, FileText, GitPullRequest, ListChecks } from "lucide-react";

const EXAMPLES = [
  { icon: FileText, title: "Research & writing", description: "From a rough idea to a useful first draft." },
  { icon: GitPullRequest, title: "Code reviews", description: "Another pair of eyes on your next pull request." },
  { icon: ListChecks, title: "Project updates", description: "Keep track of decisions, progress and next steps." },
];

export function EmptyTeam({ onReady, onCustom }: { onReady?: () => void; onCustom: () => void }) {
  return (
    <section className="col-span-full overflow-hidden rounded-2xl border" aria-labelledby="empty-team-title" style={{ background: "var(--bg-elev)", borderColor: "var(--line)" }}>
      <div className="grid md:grid-cols-[1.1fr_1fr]">
        <div className="flex flex-col items-start justify-center p-6 sm:p-10 lg:p-12">
          <p className="m-0 mb-4 text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--ink-3)" }}>A little help goes a long way</p>
          <h3 id="empty-team-title" className="m-0 max-w-sm text-3xl font-medium leading-tight tracking-tight sm:text-4xl" style={{ color: "var(--ink)" }}>
            Meet your first AI teammate.
          </h3>
          <p className="mb-7 mt-4 max-w-sm text-sm leading-relaxed" style={{ color: "var(--ink-3)" }}>
            Pick a template, give your agent a name, and make it your own. Start chatting on the web and connect more channels whenever you&apos;re ready.
          </p>
          <div className="flex flex-wrap gap-2">
            {onReady && <button type="button" aria-label="Try a ready-made assistant" onClick={onReady} className="af-btn af-btn-primary af-btn-lg">
              Ready-made assistant <ArrowRight size={16} aria-hidden="true" />
            </button>}
            <button type="button" aria-label="Hire a teammate" onClick={onCustom} className={`af-btn af-btn-lg${onReady ? "" : " af-btn-primary"}`}>Build your own</button>
          </div>
          <p className="mb-0 mt-3 text-xs" style={{ color: "var(--ink-3)" }}>You choose the template, model and runtime.</p>
        </div>
        <div className="flex flex-col justify-center gap-3 border-t p-6 sm:p-10 md:border-l md:border-t-0" style={{ background: "var(--bg-soft)", borderColor: "var(--line)" }}>
          <p className="m-0 mb-1 text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--ink-3)" }}>A few ways to start</p>
          {EXAMPLES.map(({ icon: Icon, title, description }) => (
            <div key={title} className="flex items-start gap-3 rounded-xl border p-4" style={{ background: "var(--bg-elev)", borderColor: "var(--line)" }}>
              <span className="grid size-9 shrink-0 place-items-center rounded-lg" style={{ background: "var(--bg-soft)", color: "var(--ink-2)" }}><Icon size={18} aria-hidden="true" /></span>
              <div>
                <p className="m-0 text-sm font-semibold" style={{ color: "var(--ink)" }}>{title}</p>
                <p className="mb-0 mt-1 text-xs leading-relaxed" style={{ color: "var(--ink-3)" }}>{description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
