"use client";

import { useState } from "react";
import type { Agent } from "../types";
import { SKILLS, TEMPLATE_FILES, getTemplate } from "../data";
import { PlusIcon, XIcon, LockIcon, SlackIcon } from "@/components/icons";

interface ConfigDrawerProps {
  agent: Agent;
  onClose: () => void;
}

const TABS = [
  ["personality", "Personality"],
  ["channels", "Channels"],
  ["skills", "Skills"],
  ["secrets", "Keys"],
  ["k8s", "Infrastructure"],
  ["danger", "Danger zone"],
] as const;

type TabKey = (typeof TABS)[number][0];

export function ConfigDrawer({ agent, onClose }: ConfigDrawerProps) {
  const [tab, setTab] = useState<TabKey>("personality");
  const [retireConfirm, setRetireConfirm] = useState(false);
  const templateFiles = TEMPLATE_FILES[agent.template_id] ?? {};
  const fileKeys = Object.keys(templateFiles);
  const [file, setFile] = useState(fileKeys[0] ?? "soul_md");
  const [files, setFiles] = useState<Record<string, string>>(templateFiles);

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0"
        style={{ background: "rgba(20,16,10,.4)" }}
        onClick={onClose}
      />
      <aside
        className="absolute top-0 right-0 bottom-0 flex flex-col af-drawer-panel"
        style={{ width: "min(580px, 95vw)", background: "var(--bg)", boxShadow: "var(--shadow-pop)" }}
      >
        <header className="px-[26px] pt-[22px] pb-3.5 flex items-start justify-between">
          <div>
            <div
              className="text-[12px] uppercase tracking-[0.08em] font-semibold mb-1"
              style={{ color: "var(--ink-3)" }}
            >
              {agent.name} · configuration
            </div>
            <h2 className="text-2xl font-semibold tracking-tight m-0" style={{ color: "var(--ink)" }}>
              Configure agent
            </h2>
          </div>
          <button className="af-btn af-btn-ghost af-btn-icon" onClick={onClose}>
            <XIcon />
          </button>
        </header>

        <nav
          className="flex gap-0.5 px-[18px] pt-1 overflow-x-auto flex-shrink-0 no-scrollbar"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          {TABS.map(([k, l]) => (
            <button
              key={k}
              className="af-drawer-tab"
              data-active={tab === k}
              onClick={() => setTab(k)}
            >
              {l}
            </button>
          ))}
        </nav>

        <div className="flex-1 overflow-y-auto px-[26px] py-[22px]">
          {tab === "personality" && (
            <div>
              <Hint>
                {agent.name}&apos;s personality is defined by markdown files inherited from{" "}
                <span className="font-mono">{getTemplate(agent.template_id)?.slug ?? agent.template_id}@{agent.templateVersion}</span>. Edit below to customise per-agent.
              </Hint>
              <div className="flex flex-wrap gap-1 mb-3">
                {fileKeys.map((k) => (
                  <button
                    key={k}
                    className="font-mono text-[12px] px-2.5 py-[5px] rounded-[7px] border"
                    style={{
                      background: k === file ? "var(--bg-elev)" : "transparent",
                      borderColor: k === file ? "var(--line)" : "transparent",
                      color: k === file ? "var(--ink)" : "var(--ink-3)",
                      fontWeight: k === file ? 500 : 400,
                    }}
                    onClick={() => setFile(k)}
                  >
                    {k.replace("_md", ".md")}
                  </button>
                ))}
              </div>
              <textarea
                className="w-full rounded-xl font-mono text-[12.5px] leading-[1.65] resize-none p-4"
                style={{
                  background: "var(--bg-elev)",
                  border: "1px solid var(--line)",
                  color: "var(--ink-2)",
                  outline: "none",
                  minHeight: 280,
                }}
                value={files[file] ?? ""}
                onChange={(e) => setFiles((prev) => ({ ...prev, [file]: e.target.value }))}
              />
              <div className="flex gap-2 mt-3.5">
                <button className="af-btn af-btn-sm">Save changes</button>
                <button
                  className="af-btn af-btn-sm af-btn-ghost"
                  onClick={() => setFiles(templateFiles)}
                >
                  Reset to template
                </button>
              </div>
            </div>
          )}

          {tab === "channels" && (
            <div>
              <Hint>Channels {agent.name} is allowed to read and write in.</Hint>
              <CfgRow key="#general">
                <SlackIcon style={{ color: "var(--ink-3)", flexShrink: 0 }} />
                <span className="font-mono">#general</span>
                <span className="ml-auto text-[12px]" style={{ color: "var(--ink-4)" }}>
                  read &amp; write
                </span>
                <button className="af-btn af-btn-sm af-btn-ghost">Remove</button>
              </CfgRow>
              <button className="af-btn af-btn-sm mt-3">
                <PlusIcon /> Add channel
              </button>
            </div>
          )}

          {tab === "skills" && (
            <div>
              <Hint>Tools {agent.name} can call. All vetted and routed through the egress proxy.</Hint>
              {agent.skills.map((s) => {
                const skill = SKILLS.find((x) => x.id === s);
                return (
                  <CfgRow key={s}>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium">{skill?.name ?? s}</div>
                      <div className="text-[12.5px]" style={{ color: "var(--ink-4)" }}>
                        {skill?.desc ?? ""}
                      </div>
                    </div>
                    <button className="af-btn af-btn-sm af-btn-ghost">Disable</button>
                  </CfgRow>
                );
              })}
              <button className="af-btn af-btn-sm mt-3">
                <PlusIcon /> Install skill
              </button>
            </div>
          )}

          {tab === "secrets" && (
            <div>
              <Hint>
                <LockIcon style={{ flexShrink: 0, marginTop: 1 }} /> {agent.name} only holds fake keys. The egress proxy swaps in real keys at request time and logs every swap.
              </Hint>
              <div className="flex flex-col gap-2.5">
                {[
                  ["Slack", "xoxb-fake-a91…", "2s ago"],
                  ["Atlassian", "jira-fake-b12…", "31s ago"],
                  ["Google Calendar", "gcal-fake-7c8…", "6m ago"],
                ].map(([n, k, t]) => (
                  <div
                    key={n}
                    className="grid items-center gap-3.5 px-3.5 py-3 rounded-xl"
                    style={{
                      gridTemplateColumns: "1fr auto auto",
                      border: "1px solid var(--line)",
                    }}
                  >
                    <div>
                      <div className="font-medium">{n}</div>
                      <div className="font-mono text-[12px]" style={{ color: "var(--ink-4)" }}>{k}</div>
                    </div>
                    <div className="text-[12px]" style={{ color: "var(--ink-4)" }}>used {t}</div>
                    <button className="af-btn af-btn-sm">Rotate</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {tab === "k8s" && (
            <div>
              <Hint>
                Behind the scenes, {agent.name} is a set of standard Kubernetes resources. You usually don&apos;t need to touch these.
              </Hint>
              {[
                ["Deployment", `agent-${agent.id}`, "1/1 ready"],
                ["Service", `agent-${agent.id}-svc`, "ClusterIP · :8080"],
                ["PersistentVolumeClaim", `agent-${agent.id}-workspace`, "Bound · 10Gi"],
                ["ConfigMap", `agent-${agent.id}-config`, "8 keys"],
                ["Secret", `agent-${agent.id}-secret`, "4 keys · encrypted"],
                ["NetworkPolicy", `agent-${agent.id}-egress`, "proxy + litellm only"],
              ].map(([kind, name, status]) => (
                <div
                  key={kind}
                  className="px-3.5 py-3 rounded-xl mb-1.5"
                  style={{ border: "1px solid var(--line)" }}
                >
                  <div className="font-mono text-[11.5px]" style={{ color: "var(--ink-4)" }}>{kind}</div>
                  <div className="font-mono text-[13px] font-medium" style={{ color: "var(--ink)" }}>{name}</div>
                  <div className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>{status}</div>
                </div>
              ))}
            </div>
          )}

          {tab === "danger" && (
            <div>
              <Hint>Permanent actions. Pause first if you&apos;re not sure.</Hint>
              <div className="flex gap-2 flex-wrap mt-2">
                <button className="af-btn">Restart agent</button>
                <button className="af-btn">Reset workspace</button>
                <button
                  className="af-btn"
                  style={{ borderColor: "var(--err)", color: "var(--err)" }}
                  onClick={() => setRetireConfirm(true)}
                >
                  Retire agent
                </button>
              </div>
              <div className="text-[12px] mt-2.5 leading-[1.5]" style={{ color: "var(--ink-4)" }}>
                Retiring permanently deletes all pods, volumes, and configuration.
              </div>
            </div>
          )}
        </div>
      </aside>

      {retireConfirm && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div
            className="absolute inset-0"
            style={{ background: "rgba(20,16,10,.5)" }}
            onClick={() => setRetireConfirm(false)}
          />
          <div
            className="relative w-full max-w-sm rounded-2xl p-6 shadow-2xl"
            style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
          >
            <h3 className="text-[17px] font-semibold tracking-tight mb-1.5" style={{ color: "var(--ink)" }}>
              Retire {agent.name}?
            </h3>
            <p className="text-[13.5px] leading-[1.55] mb-6" style={{ color: "var(--ink-3)" }}>
              This will permanently delete {agent.name}&apos;s pods, volumes, and configuration. This cannot be undone.
            </p>
            <div className="flex gap-2 justify-end">
              <button className="af-btn af-btn-ghost" onClick={() => setRetireConfirm(false)}>
                Cancel
              </button>
              <button
                className="af-btn"
                style={{ background: "var(--err)", borderColor: "var(--err)", color: "#fff" }}
              >
                Retire agent
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-[13px] rounded-xl px-3.5 py-3 mb-[18px] leading-[1.5] flex items-start gap-1.5"
      style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
    >
      {children}
    </div>
  );
}

function CfgRow({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex items-center gap-2.5 px-3.5 py-[11px] text-[13.5px]"
      style={{ borderBottom: "1px solid var(--line)" }}
    >
      {children}
    </div>
  );
}

