"use client";

import type { ReactNode } from "react";
import { CircleAlert, Info, PlugZap } from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/badge";
import { LockIcon } from "@/components/icons";

import type { McpSignIn } from "../schemas";
import { signInLabel } from "../utils";

/** The on/off switch used across settings surfaces. */
export function McpSwitch({
  checked,
  label,
  disabled = false,
  title,
  onChange,
}: {
  checked: boolean;
  label: string;
  disabled?: boolean;
  title?: string;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={title}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50"
      style={{ backgroundColor: checked ? "var(--ink)" : "var(--line)" }}
    >
      <span
        className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${checked ? "translate-x-4" : ""}`}
      />
    </button>
  );
}

/** A labelled form control, in the shape the other settings dialogs use. */
export function McpField({
  id,
  label,
  hint,
  children,
}: {
  id?: string;
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[0.8rem] font-medium" style={{ color: "var(--ink-2)" }} htmlFor={id}>
        {label}
      </label>
      {children}
      {hint && (
        <p className="m-0 text-[0.76rem]" style={{ color: "var(--ink-4)" }}>
          {hint}
        </p>
      )}
    </div>
  );
}

/** A titled group of fields inside a dialog. */
export function McpFieldGroup({
  title,
  description,
  children,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3.5 border-t pt-4" style={{ borderColor: "var(--line)" }}>
      <div>
        <h3 className="m-0 text-[0.86rem] font-semibold" style={{ color: "var(--ink)" }}>
          {title}
        </h3>
        {description && (
          <p className="mb-0 mt-0.5 text-[0.78rem]" style={{ color: "var(--ink-3)" }}>
            {description}
          </p>
        )}
      </div>
      {children}
    </div>
  );
}

const NOTICE_TONES = {
  info: { background: "var(--bg-soft)", color: "var(--ink-3)", border: "transparent", Icon: Info },
  warn: {
    background: "var(--warn-soft)",
    color: "var(--warn)",
    border: "color-mix(in srgb, var(--warn) 30%, transparent)",
    Icon: CircleAlert,
  },
  error: {
    background: "var(--err-soft)",
    color: "var(--err)",
    border: "color-mix(in srgb, var(--err) 30%, transparent)",
    Icon: CircleAlert,
  },
} as const;

/** An inline note or error, matching the boxes other settings forms use. */
export function McpNotice({
  tone = "info",
  title,
  children,
}: {
  tone?: keyof typeof NOTICE_TONES;
  title?: string;
  children: ReactNode;
}) {
  const style = NOTICE_TONES[tone];
  return (
    <div
      className="flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-[0.8rem] leading-[1.5]"
      style={{ background: style.background, color: style.color, borderColor: style.border }}
      role={tone === "error" ? "alert" : undefined}
    >
      <style.Icon size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="min-w-0">
        {title && <p className="m-0 font-medium">{title}</p>}
        <div className="m-0">{children}</div>
      </div>
    </div>
  );
}

/** The dashed empty state the other connection lists show. */
export function McpEmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-[var(--line-strong)] p-6 text-center">
      <PlugZap size={20} className="text-[var(--ink-4)]" aria-hidden="true" />
      <p className="m-0 text-sm font-medium text-[var(--ink)]">{title}</p>
      <div className="m-0 max-w-md text-sm text-[var(--ink-3)]">{children}</div>
    </div>
  );
}

/** The row icon, in the accent colour other connection rows use. */
export function McpServerIcon() {
  return (
    <span
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
      style={{ background: "var(--accent-soft)", color: "var(--accent-ink)" }}
      aria-hidden="true"
    >
      <PlugZap size={15} />
    </span>
  );
}

const SIGN_IN_VARIANT: Record<McpSignIn["status"], BadgeVariant> = {
  signed_in: "ok",
  needs_sign_in: "danger",
  not_signed_in: "warn",
};

export function SignInBadge({ signIn }: { signIn: McpSignIn }) {
  return <Badge variant={SIGN_IN_VARIANT[signIn.status]}>{signInLabel(signIn)}</Badge>;
}

export function RestrictedBadge() {
  return (
    <Badge title="Only organization Owners and Admins can change it for an Agent">
      <LockIcon size={10} /> Restricted
    </Badge>
  );
}

export { Badge };
