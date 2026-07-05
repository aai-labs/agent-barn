import React from "react";

interface IconProps {
  size?: number;
  className?: string;
  style?: React.CSSProperties;
}

function Svg({
  size = 14,
  className,
  style,
  strokeWidth = 1.7,
  children,
}: IconProps & { strokeWidth?: number; children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={style}
    >
      {children}
    </svg>
  );
}

export function PlusIcon(p: IconProps) {
  return <Svg {...p}><path d="M12 5v14M5 12h14"/></Svg>;
}

export function XIcon({ size = 16, ...p }: IconProps) {
  return <Svg size={size} {...p}><path d="M6 6l12 12M18 6 6 18"/></Svg>;
}

export function CheckIcon({ size = 16, ...p }: IconProps) {
  return <Svg size={size} strokeWidth={2} {...p}><path d="m5 12 5 5L20 7"/></Svg>;
}

export function CogIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>
    </Svg>
  );
}

export function LockIcon({ size = 13, ...p }: IconProps) {
  return <Svg size={size} {...p}><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></Svg>;
}

export function SlackIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M14 10V5a2 2 0 1 1 4 0v5h-4z"/>
      <path d="M14 14h5a2 2 0 1 1 0 4h-5v-4z"/>
      <path d="M10 14v5a2 2 0 1 1-4 0v-5h4z"/>
      <path d="M10 10H5a2 2 0 1 1 0-4h5v4z"/>
    </Svg>
  );
}

export function TeamsIcon({ size = 14, ...p }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      className={p.className}
      style={p.style}
    >
      <path d="M13.5 4.5a2.5 2.5 0 1 1 5 0 2.5 2.5 0 0 1-5 0Zm6.7 3.5h-3.9a3.5 3.5 0 0 1-.3 1.3h3.6c.55 0 1 .45 1 1v3.7a2.7 2.7 0 0 1-2.4 2.68c-.32 1.6-1.32 2.96-2.7 3.74A4.2 4.2 0 0 0 16 16.6V9.3c0-.72.58-1.3 1.3-1.3h2.9c.99 0 1.8.81 1.8 1.8v2.5a3.3 3.3 0 0 1-2 3.03V9.3a.3.3 0 0 0-.3-.3Z" />
      <path d="M3 6.4h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1Zm2.1 2.5v1.45h2.05v5.25h1.7V10.35h2.05V8.9H5.1Z" />
    </svg>
  );
}

export function ChevLeftIcon(p: IconProps) {
  return <Svg {...p}><path d="m15 18-6-6 6-6"/></Svg>;
}

export function ChevronDownIcon(p: IconProps) {
  return <Svg {...p}><path d="m6 9 6 6 6-6"/></Svg>;
}

export function PauseIcon(p: IconProps) {
  return <Svg {...p}><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></Svg>;
}

export function PlayIcon(p: IconProps) {
  return <Svg {...p}><polygon points="6 3 20 12 6 21 6 3"/></Svg>;
}

export function LinkIcon(p: IconProps) {
  return <Svg {...p}><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></Svg>;
}

export function SearchIcon(p: IconProps) {
  return <Svg {...p}><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></Svg>;
}

export function ShieldIcon({ size = 13, ...p }: IconProps) {
  return <Svg size={size} {...p}><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/></Svg>;
}

export function EyeIcon({ size = 13, ...p }: IconProps) {
  return <Svg size={size} {...p}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></Svg>;
}

export function EyeOffIcon({ size = 13, ...p }: IconProps) {
  return <Svg size={size} {...p}><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></Svg>;
}

export function ServerIcon({ size = 13, ...p }: IconProps) {
  return <Svg size={size} {...p}><rect x="3" y="4" width="18" height="6" rx="1"/><rect x="3" y="14" width="18" height="6" rx="1"/><path d="M7 7h.01M7 17h.01"/></Svg>;
}

export function UserIcon(p: IconProps) {
  return <Svg {...p}><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></Svg>;
}

export function UsersIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
      <circle cx="9" cy="7" r="4"/>
      <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>
    </Svg>
  );
}

export function BuildingIcon(p: IconProps) {
  return <Svg {...p}><path d="M3 21h18M3 7l9-4 9 4M4 7v14M20 7v14M9 21V12h6v9"/></Svg>;
}

export function AlertCircleIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="8" x2="12" y2="12"/>
      <line x1="12" y1="16" x2="12.01" y2="16"/>
    </Svg>
  );
}

export function LogOutIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
      <polyline points="16 17 21 12 16 7"/>
      <line x1="21" y1="12" x2="9" y2="12"/>
    </Svg>
  );
}

export function KeyIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="m21 2-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4"/>
    </Svg>
  );
}
