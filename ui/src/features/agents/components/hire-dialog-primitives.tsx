"use client";

import React from "react";
import { EyeIcon, EyeOffIcon } from "@/components/icons";

export function DialogShell({
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

export function ChoiceCard({
  selected,
  onClick,
  title,
  description,
}: {
  selected: boolean;
  onClick: () => void;
  title: string;
  description: string;
}) {
  return (
    <div
      className="flex flex-col gap-1 p-4 rounded-2xl cursor-default transition-colors"
      style={{
        border: selected ? "1.5px solid var(--ink)" : "1.5px solid var(--line)",
        background: selected ? "var(--bg-soft)" : "var(--bg-elev)",
      }}
      onClick={onClick}
    >
      <div className="font-semibold text-[0.9375rem]" style={{ color: "var(--ink)" }}>{title}</div>
      <div className="text-[0.8125rem] leading-[1.45]" style={{ color: "var(--ink-3)" }}>{description}</div>
    </div>
  );
}

export function FormField({
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
      <label className="font-medium text-[0.844rem]" style={{ color: "var(--ink)" }}>
        {label}
      </label>
      {children}
      {hint && (
        <span className="text-xs" style={{ color: "var(--ink-4)" }}>
          {hint}
        </span>
      )}
    </div>
  );
}

export function TokenInput({
  value,
  onChange,
  visible,
  onToggle,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  visible: boolean;
  onToggle: () => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <div className="relative">
      <input
        className="af-input font-mono text-[0.8125rem] pr-10"
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        disabled={disabled}
      />
      <button
        type="button"
        className="absolute right-3 top-1/2 -translate-y-1/2"
        style={{ color: "var(--ink-4)" }}
        onClick={onToggle}
        tabIndex={-1}
      >
        {visible ? <EyeOffIcon size={15} /> : <EyeIcon size={15} />}
      </button>
    </div>
  );
}

export function NextStep({
  n,
  label,
  children,
}: {
  n: number;
  label: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex gap-3 items-start">
      <div
        className="w-5 h-5 rounded-full flex-shrink-0 grid place-items-center text-[0.656rem] font-bold mt-0.5"
        style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", color: "var(--ink-3)" }}
      >
        {n}
      </div>
      <div>
        <div className="font-medium text-[0.8125rem] mb-0.5" style={{ color: "var(--ink)" }}>{label}</div>
        {children && (
          <div className="text-[0.781rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>{children}</div>
        )}
      </div>
    </div>
  );
}
