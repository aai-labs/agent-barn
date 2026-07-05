"use client";

import { Copy } from "lucide-react";
import { toast } from "sonner";

interface InviteLinkFieldProps {
  link: string;
  label?: string;
}

/**
 * Read-only invite link with a copy button. Shown after creating an org / adding or
 * resending a member invite, so an admin can deliver the link manually.
 */
export function InviteLinkField({
  link,
  label = "Invite link",
}: InviteLinkFieldProps) {
  const handleCopy = async () => {
    await navigator.clipboard.writeText(link);
    toast.success("Invite link copied to clipboard");
  };

  return (
    <div>
      <label
        className="mb-1.5 block text-[13.5px] font-medium"
        style={{ color: "var(--ink)" }}
      >
        {label}
      </label>
      <div className="flex gap-1.5">
        <input
          readOnly
          value={link}
          className="af-input flex-1 text-[12.5px]"
          onFocus={(e) => e.currentTarget.select()}
        />
        <button
          type="button"
          className="af-btn"
          onClick={() => void handleCopy()}
          title="Copy link"
        >
          <Copy width={14} height={14} />
        </button>
      </div>
      <p className="mt-1.5 text-[12px]" style={{ color: "var(--ink-4)" }}>
        An invite email was also sent. This link lets you share it directly.
      </p>
    </div>
  );
}
