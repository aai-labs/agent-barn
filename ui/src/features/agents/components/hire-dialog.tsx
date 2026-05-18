"use client";

import { useState, useEffect } from "react";
import { TEMPLATE_FILES } from "../data";
import { XIcon, CheckIcon } from "@/components/icons";

interface HireDialogProps {
  onClose: () => void;
  onHired: (info: { name: string; role: string }) => void;
}

const ROLES = [
  { id: "default", template_id: "t_default", title: "General Purpose", emoji: "🤖", tagline: "Answers questions, handles tasks, reduces day-to-day friction.", suggested: "Aria" },
  { id: "code-reviewer", template_id: "t_reviewer", title: "PR Reviewer", emoji: "⚙️", tagline: "Reads diffs, comments on style, security, and tests.", suggested: "Halo" },
  { id: "analyst", template_id: "t_analyst", title: "Data Analyst", emoji: "📊", tagline: "Answers questions over BigQuery & Sheets, returns charts.", suggested: "Lyra" },
  { id: "sales-research", template_id: "t_sales", title: "Sales Research", emoji: "📈", tagline: "Enriches leads, drafts outbound, summarises calls.", suggested: "Vega" },
] as const;

type RoleId = (typeof ROLES)[number]["id"];

const PROVISION_STEPS = [
  { at: 14, text: "Resolved template" },
  { at: 32, text: "Created workspace and config" },
  { at: 50, text: "Issued provider keys (vaulted)" },
  { at: 68, text: "Locked network egress" },
  { at: 84, text: "Started agent" },
  { at: 96, text: "", isPending: true },
];

function pickDefaults(roleId: RoleId) {
  const role = ROLES.find((r) => r.id === roleId)!;
  const tpl = TEMPLATE_FILES[role.template_id] ?? {};
  return { name: role.suggested, soulMd: tpl.soul_md ?? "", identityMd: tpl.identity_md ?? "", userMd: tpl.user_md ?? "", toolsMd: tpl.tools_md ?? "" };
}

export function HireDialog({ onClose, onHired }: HireDialogProps) {
  const [step, setStep] = useState(0);
  const [pick, setPick] = useState<RoleId>("default");
  const defaults = pickDefaults("default");
  const [name, setName] = useState<string>(defaults.name);
  const [slackAppToken, setSlackAppToken] = useState("");
  const [slackBotToken, setSlackBotToken] = useState("");
  const [soulMd, setSoulMd] = useState(defaults.soulMd);
  const [identityMd, setIdentityMd] = useState(defaults.identityMd);
  const [userMd, setUserMd] = useState(defaults.userMd);
  const [toolsMd, setToolsMd] = useState(defaults.toolsMd);
  const [provisioning, setProvisioning] = useState(false);
  const [progress, setProgress] = useState(0);

  const selected = ROLES.find((r) => r.id === pick)!;

  function handlePickRole(roleId: RoleId) {
    const d = pickDefaults(roleId);
    setPick(roleId);
    setName(d.name);
    setSoulMd(d.soulMd);
    setIdentityMd(d.identityMd);
    setUserMd(d.userMd);
    setToolsMd(d.toolsMd);
  }

  useEffect(() => {
    if (!provisioning) return;
    let v = 0;
    const id = setInterval(() => {
      v += 8 + Math.random() * 12;
      if (v >= 100) {
        v = 100;
        clearInterval(id);
        setTimeout(() => onHired({ name, role: selected.title }), 500);
      }
      setProgress(v);
    }, 240);
    return () => clearInterval(id);
  }, [provisioning]); // eslint-disable-line react-hooks/exhaustive-deps

  if (provisioning) {
    return (
      <DialogShell shadeClick={undefined}>
        <div className="flex flex-col items-center text-center py-12 px-8">
          <div className="text-6xl mb-6">{selected.emoji}</div>
          <h2 className="text-2xl font-semibold tracking-tight mb-2" style={{ color: "var(--ink)" }}>
            Hiring {name}…
          </h2>
          <p className="text-[14px] mb-8" style={{ color: "var(--ink-3)" }}>
            A few moments — provisioning, installing skills, connecting to Slack.
          </p>
          <div className="w-full max-w-sm mb-8">
            <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-soft)" }}>
              <div
                className="h-full rounded-full transition-all duration-300"
                style={{ width: `${progress}%`, background: "var(--ink)" }}
              />
            </div>
          </div>
          <div className="flex flex-col gap-2.5 text-left w-full max-w-sm">
            {PROVISION_STEPS.map((s, i) => {
              const done = progress >= s.at;
              const pending = s.isPending && done && progress < 100;
              const text = s.isPending ? `${name} said hello in Slack` : s.text;
              return (
                <div key={i} className="flex items-center gap-3 text-[13.5px]">
                  <div className="w-5 h-5 flex-shrink-0 grid place-items-center">
                    {pending ? (
                      <div className="w-4 h-4 rounded-full border-2 border-t-transparent animate-spin" style={{ borderColor: "var(--ink-3)", borderTopColor: "transparent" }} />
                    ) : done ? (
                      <CheckIcon style={{ color: "var(--ok)" }} />
                    ) : (
                      <div className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--ink-5)" }} />
                    )}
                  </div>
                  <span style={{ color: done ? "var(--ink)" : "var(--ink-4)" }}>{text}</span>
                </div>
              );
            })}
          </div>
        </div>
      </DialogShell>
    );
  }

  return (
    <DialogShell shadeClick={onClose}>
      <header
        className="px-6 pt-6 pb-4 flex items-start justify-between"
        style={{ borderBottom: "1px solid var(--line)" }}
      >
        <div>
          <div className="text-[12px] uppercase tracking-[0.08em] font-semibold mb-1" style={{ color: "var(--ink-3)" }}>
            Hire · step {step + 1} of 2
          </div>
          <h2 className="text-xl font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
            {step === 0 ? "What kind of teammate do you need?" : "A few details and we'll get them set up."}
          </h2>
        </div>
        <button className="af-btn af-btn-ghost af-btn-icon" onClick={onClose}>
          <XIcon />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        {step === 0 && (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            {ROLES.map((r) => (
              <div
                key={r.id}
                className="flex flex-col gap-2 p-4 rounded-2xl cursor-default transition-colors"
                style={{
                  border: pick === r.id ? "1.5px solid var(--ink)" : "1.5px solid var(--line)",
                  background: pick === r.id ? "var(--bg-soft)" : "var(--bg-elev)",
                }}
                onClick={() => handlePickRole(r.id)}
              >
                <div className="text-2xl">{r.emoji}</div>
                <div className="font-semibold text-[13.5px]" style={{ color: "var(--ink)" }}>{r.title}</div>
                <div className="text-[12.5px] leading-[1.4]" style={{ color: "var(--ink-3)" }}>{r.tagline}</div>
              </div>
            ))}
          </div>
        )}

        {step === 1 && (
          <div className="flex flex-col gap-5">
            <div
              className="flex items-center gap-3 p-4 rounded-2xl"
              style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
            >
              <div className="text-2xl">{selected.emoji}</div>
              <div className="flex-1">
                <div className="font-semibold text-[14px]" style={{ color: "var(--ink)" }}>{selected.title}</div>
                <div className="text-[13px]" style={{ color: "var(--ink-3)" }}>{selected.tagline}</div>
              </div>
              <button className="af-btn af-btn-sm af-btn-ghost" onClick={() => setStep(0)}>Change</button>
            </div>

            <FormField label="Name them" hint={`Suggested: ${selected.suggested}`}>
              <input
                className="af-input af-input-lg"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={selected.suggested}
              />
            </FormField>

            <div
              className="flex flex-col gap-3.5 p-4 rounded-2xl"
              style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
            >
              <div>
                <div className="font-semibold text-[13.5px] mb-0.5" style={{ color: "var(--ink)" }}>
                  Slack connection
                </div>
                <div className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
                  These credentials stay encrypted in the key vault. The agent only sees fake placeholders.
                </div>
              </div>

              <FormField label="App-level token" hint="Starts with xapp- · required for Socket Mode">
                <input
                  className="af-input font-mono text-[13px]"
                  type="password"
                  value={slackAppToken}
                  onChange={(e) => setSlackAppToken(e.target.value)}
                  placeholder="xapp-1-…"
                  autoComplete="off"
                />
              </FormField>

              <FormField label="Bot token" hint="Starts with xoxb- · required for API calls">
                <input
                  className="af-input font-mono text-[13px]"
                  type="password"
                  value={slackBotToken}
                  onChange={(e) => setSlackBotToken(e.target.value)}
                  placeholder="xoxb-…"
                  autoComplete="off"
                />
              </FormField>
            </div>

            <details className="rounded-2xl overflow-hidden" style={{ border: "1px solid var(--line)" }}>
              <summary
                className="px-4 py-3 text-[13.5px] font-medium cursor-default"
                style={{ color: "var(--ink-2)", background: "var(--bg-elev)" }}
              >
                Review configuration files
              </summary>
              <div className="p-4 flex flex-col gap-4" style={{ background: "var(--bg-soft)" }}>
                <div className="text-[12.5px] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
                  Pre-populated from the <span className="font-mono">{selected.id}</span> template. Edit before hiring to customise.
                </div>
                <FormField label="soul.md" hint="Core purpose and values — required">
                  <textarea className="af-input font-mono text-[12.5px] leading-[1.65] resize-none" rows={7} value={soulMd} onChange={(e) => setSoulMd(e.target.value)} />
                </FormField>
                <FormField label="identity.md" hint="Voice, tone, and hard boundaries — required">
                  <textarea className="af-input font-mono text-[12.5px] leading-[1.65] resize-none" rows={7} value={identityMd} onChange={(e) => setIdentityMd(e.target.value)} />
                </FormField>
                <FormField label="user.md" hint="Who this agent talks to">
                  <textarea className="af-input font-mono text-[12.5px] leading-[1.65] resize-none" rows={5} value={userMd} onChange={(e) => setUserMd(e.target.value)} />
                </FormField>
                <FormField label="tools.md" hint="Available tools">
                  <textarea className="af-input font-mono text-[12.5px] leading-[1.65] resize-none" rows={5} value={toolsMd} onChange={(e) => setToolsMd(e.target.value)} />
                </FormField>
              </div>
            </details>
          </div>
        )}
      </div>

      <footer
        className="px-6 py-4 flex items-center justify-between flex-shrink-0"
        style={{ borderTop: "1px solid var(--line)" }}
      >
        {step === 0 ? (
          <button className="af-btn af-btn-ghost" onClick={onClose}>Cancel</button>
        ) : (
          <button className="af-btn" onClick={() => setStep(0)}>Back</button>
        )}
        {step === 0 ? (
          <button className="af-btn af-btn-primary af-btn-lg" onClick={() => setStep(1)}>
            Continue
          </button>
        ) : (
          <button
            className="af-btn af-btn-primary af-btn-lg"
            onClick={() => setProvisioning(true)}
          >
            Hire {name}
          </button>
        )}
      </footer>
    </DialogShell>
  );
}

function DialogShell({
  children,
  shadeClick,
}: {
  children: React.ReactNode;
  shadeClick: (() => void) | undefined;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0"
        style={{ background: "rgba(20,16,10,.4)" }}
        onClick={shadeClick}
      />
      <div
        className="relative flex flex-col w-full max-w-2xl max-h-[90vh] rounded-2xl shadow-2xl"
        style={{ background: "var(--bg-elev)" }}
      >
        {children}
      </div>
    </div>
  );
}

function FormField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="font-medium text-[13.5px]" style={{ color: "var(--ink)" }}>
        {label}
      </label>
      {children}
      {hint && (
        <span className="text-[12px]" style={{ color: "var(--ink-4)" }}>
          {hint}
        </span>
      )}
    </div>
  );
}

