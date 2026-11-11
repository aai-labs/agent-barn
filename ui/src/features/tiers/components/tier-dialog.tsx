"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

import { useTierActions } from "../hooks/use-tiers";
import type { Tier, TierActivation, TierValues } from "../schemas";
import { ACTIVATION_LABELS, MAX_AGENT_LIMIT, MAX_AMOUNT_USD, TIER_FEATURES, TIER_PLATFORMS } from "../utils";

const AMOUNT = /^\d+(\.\d{1,2})?$/;
const WHOLE = /^\d+$/;
const KEY = /^[a-z][a-z0-9_]{1,31}$/;

type Draft = {
  key: string;
  activation: TierActivation;
  name: string;
  tagline: string;
  price: string;
  priceNote: string;
  monthlyUsage: string;
  oneTimeCredit: string;
  agentLimit: string;
  everyPlatform: boolean;
  platforms: string[];
  features: string[];
  contactUrl: string;
};

type FieldKey = "key" | "name" | "price" | "monthlyUsage" | "oneTimeCredit" | "agentLimit" | "platforms" | "contactUrl";

function draftOf(tier: Tier | null): Draft {
  if (!tier) {
    return {
      key: "",
      activation: "paid",
      name: "",
      tagline: "",
      price: "",
      priceNote: "per month",
      monthlyUsage: "",
      oneTimeCredit: "0",
      agentLimit: "1",
      everyPlatform: true,
      platforms: [],
      features: TIER_FEATURES.filter((feature) => feature.key !== "priority_support").map((feature) => feature.key),
      contactUrl: "",
    };
  }
  return {
    key: tier.key,
    activation: tier.activation,
    name: tier.name,
    tagline: tier.tagline ?? "",
    price: tier.priceUsd,
    priceNote: tier.priceNote ?? "",
    monthlyUsage: tier.monthlyUsageUsd,
    oneTimeCredit: tier.oneTimeCreditUsd,
    agentLimit: String(tier.agentLimit),
    everyPlatform: tier.allowedPlatformKeys === null,
    platforms: tier.allowedPlatformKeys ?? [],
    features: tier.features,
    contactUrl: tier.contactUrl ?? "",
  };
}

/** Which fields mean something for a tier activated this way. */
function shows(activation: TierActivation) {
  return {
    price: activation === "paid" || activation === "contact",
    monthlyUsage: activation === "paid",
    contactUrl: activation === "contact",
  };
}

function amount(raw: string): number | null {
  const value = raw.trim();
  if (!AMOUNT.test(value)) return null;
  const parsed = Number(value);
  return parsed <= MAX_AMOUNT_USD ? parsed : null;
}

/** The values the draft describes, or why they can't be used, per field. */
function parse(draft: Draft, creating: boolean): { values: TierValues | null; errors: Partial<Record<FieldKey, string>> } {
  const errors: Partial<Record<FieldKey, string>> = {};
  const visible = shows(draft.activation);
  const amountError = `Enter dollars and cents from 0 to ${MAX_AMOUNT_USD.toLocaleString()}.`;

  if (creating && !KEY.test(draft.key)) {
    errors.key = "Use 2–32 lowercase letters, digits and underscores, starting with a letter.";
  }
  const name = draft.name.trim();
  if (!name) errors.name = "Give the tier a name.";

  const price = visible.price ? amount(draft.price) : 0;
  if (price === null) errors.price = amountError;
  else if (draft.activation === "paid" && price <= 0) errors.price = "A paid tier needs a price above zero.";

  const monthlyUsage = visible.monthlyUsage ? amount(draft.monthlyUsage) : 0;
  if (monthlyUsage === null) errors.monthlyUsage = amountError;

  const oneTimeCredit = amount(draft.oneTimeCredit);
  if (oneTimeCredit === null) errors.oneTimeCredit = amountError;

  const limit = WHOLE.test(draft.agentLimit.trim()) ? Number(draft.agentLimit.trim()) : Number.NaN;
  if (!(limit >= 1 && limit <= MAX_AGENT_LIMIT)) {
    errors.agentLimit = `Enter a whole number of agents from 1 to ${MAX_AGENT_LIMIT}.`;
  }

  if (!draft.everyPlatform && draft.platforms.length === 0) {
    errors.platforms = "Choose at least one platform, or allow every platform.";
  }

  const contactUrl = draft.contactUrl.trim();
  if (visible.contactUrl && !/^https:\/\/\S+\.\S+/.test(contactUrl)) {
    errors.contactUrl = "Enter a link starting with https://.";
  }

  if (Object.keys(errors).length) return { values: null, errors };
  return {
    values: {
      name,
      tagline: draft.tagline.trim() || null,
      priceUsd: (price ?? 0).toFixed(2),
      priceNote: visible.price ? draft.priceNote.trim() || null : null,
      monthlyUsageUsd: (monthlyUsage ?? 0).toFixed(2),
      oneTimeCreditUsd: (oneTimeCredit ?? 0).toFixed(2),
      agentLimit: limit,
      allowedPlatformKeys: draft.everyPlatform ? null : draft.platforms,
      features: draft.features,
      contactUrl: visible.contactUrl ? contactUrl : null,
    },
    errors,
  };
}

function toggled(list: string[], key: string, on: boolean): string[] {
  return on ? [...new Set([...list, key])] : list.filter((item) => item !== key);
}

/**
 * Add a tier to the catalog, or edit one. A change to an existing tier reaches every
 * organization on it straight away; a price change applies only to new subscriptions.
 */
export function TierDialog({
  tier,
  open,
  onOpenChange,
}: {
  /** The tier to edit, or null to add one. */
  tier: Tier | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  // Keyed on each opening by the parent, so the form starts from what is saved.
  const [draft, setDraft] = useState(() => draftOf(tier));
  const [showErrors, setShowErrors] = useState(false);
  const { create, update } = useTierActions();
  const creating = tier === null;
  const mutation = creating ? create : update;
  const { values, errors } = parse(draft, creating);
  const visible = shows(draft.activation);
  const shownError = (key: FieldKey) => (showErrors ? errors[key] : undefined);
  const change = (next: Partial<Draft>) => setDraft((current) => ({ ...current, ...next }));

  function save() {
    setShowErrors(true);
    if (!values) return;
    const done = { onSuccess: () => onOpenChange(false) };
    if (tier) {
      update.mutate({ id: tier.id, data: values }, done);
    } else {
      create.mutate(
        { ...values, key: draft.key, activation: draft.activation === "contact" ? "contact" : "paid" },
        done,
      );
    }
  }

  const failure = mutation.error ? getErrorDisplay(mutation.error).description : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl" data-testid="tier-dialog">
        <DialogHeader>
          <DialogTitle>{tier ? `Edit ${tier.name}` : "Add a tier"}</DialogTitle>
          <DialogDescription>
            {tier
              ? "Limits and features change for every organization on this tier straight away. A new price applies to new subscriptions only."
              : "A new tier is off until you turn it on, so nobody is offered it while you set it up."}
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          {creating && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="tier-key" label="Key" error={shownError("key")} help="Used in links and analytics; can't be changed.">
                <input
                  id="tier-key"
                  type="text"
                  className="af-input w-full"
                  value={draft.key}
                  maxLength={32}
                  onChange={(event) => change({ key: event.target.value })}
                  placeholder="e.g. cloud_3"
                  autoComplete="off"
                  aria-invalid={!!shownError("key")}
                />
              </Field>
              <Field id="tier-activation" label="How organizations get it" help="Can't be changed later.">
                <Select
                  value={draft.activation}
                  onValueChange={(value) => change({ activation: value as TierActivation })}
                >
                  <SelectTrigger id="tier-activation" aria-label="How organizations get it" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value="paid">{ACTIVATION_LABELS.paid}</SelectItem>
                      <SelectItem value="contact">{ACTIVATION_LABELS.contact}</SelectItem>
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
            </div>
          )}

          <Field id="tier-name" label="Name" error={shownError("name")}>
            <input
              id="tier-name"
              type="text"
              className="af-input w-full"
              value={draft.name}
              maxLength={64}
              onChange={(event) => change({ name: event.target.value })}
              placeholder="e.g. Cloud Tier 3"
              autoComplete="off"
              aria-invalid={!!shownError("name")}
            />
          </Field>
          <Field id="tier-tagline" label="Tagline" help="One line shown with the tier when it's offered.">
            <input
              id="tier-tagline"
              type="text"
              className="af-input w-full"
              value={draft.tagline}
              maxLength={200}
              onChange={(event) => change({ tagline: event.target.value })}
              autoComplete="off"
            />
          </Field>

          {visible.price && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                id="tier-price"
                label="Price (USD)"
                error={shownError("price")}
                help={draft.activation === "contact" ? "Shown only; nothing is charged in the product." : "Charged every month."}
              >
                <input
                  id="tier-price"
                  type="text"
                  inputMode="decimal"
                  className="af-input w-full"
                  value={draft.price}
                  onChange={(event) => change({ price: event.target.value })}
                  aria-invalid={!!shownError("price")}
                />
              </Field>
              <Field id="tier-price-note" label="Price note" help='Read after the price, e.g. "per month".'>
                <input
                  id="tier-price-note"
                  type="text"
                  className="af-input w-full"
                  value={draft.priceNote}
                  maxLength={64}
                  onChange={(event) => change({ priceNote: event.target.value })}
                  autoComplete="off"
                />
              </Field>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            {visible.monthlyUsage && (
              <Field
                id="tier-monthly-usage"
                label="Monthly usage (USD)"
                error={shownError("monthlyUsage")}
                help="Credit granted on every paid month. What's unused expires when the month ends."
              >
                <input
                  id="tier-monthly-usage"
                  type="text"
                  inputMode="decimal"
                  className="af-input w-full"
                  value={draft.monthlyUsage}
                  onChange={(event) => change({ monthlyUsage: event.target.value })}
                  aria-invalid={!!shownError("monthlyUsage")}
                />
              </Field>
            )}
            <Field
              id="tier-one-time-credit"
              label="One-time credit (USD)"
              error={shownError("oneTimeCredit")}
              help="Granted once, when an organization first comes onto the tier."
            >
              <input
                id="tier-one-time-credit"
                type="text"
                inputMode="decimal"
                className="af-input w-full"
                value={draft.oneTimeCredit}
                onChange={(event) => change({ oneTimeCredit: event.target.value })}
                aria-invalid={!!shownError("oneTimeCredit")}
              />
            </Field>
            <Field
              id="tier-agent-limit"
              label="Agents"
              error={shownError("agentLimit")}
              help="How many live agents an organization on this tier may run."
            >
              <input
                id="tier-agent-limit"
                type="text"
                inputMode="numeric"
                className="af-input w-full"
                value={draft.agentLimit}
                onChange={(event) => change({ agentLimit: event.target.value })}
                aria-invalid={!!shownError("agentLimit")}
              />
            </Field>
          </div>

          {visible.contactUrl && (
            <Field
              id="tier-contact-url"
              label="Contact link"
              error={shownError("contactUrl")}
              help="Where people go to talk to you about this tier. It is never activated automatically."
            >
              <input
                id="tier-contact-url"
                type="url"
                className="af-input w-full"
                value={draft.contactUrl}
                maxLength={500}
                onChange={(event) => change({ contactUrl: event.target.value })}
                placeholder="https://"
                autoComplete="off"
                aria-invalid={!!shownError("contactUrl")}
              />
            </Field>
          )}

          <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
            <legend className="mb-1.5 text-[0.8rem] font-medium" style={{ color: "var(--ink-2)" }}>
              Platforms
            </legend>
            <CheckboxRow
              id="tier-every-platform"
              label="Every platform"
              checked={draft.everyPlatform}
              onChange={(on) => change({ everyPlatform: on })}
            />
            {!draft.everyPlatform && (
              <div className="grid gap-2 pl-6 sm:grid-cols-2">
                {TIER_PLATFORMS.map((platform) => (
                  <CheckboxRow
                    key={platform.key}
                    id={`tier-platform-${platform.key}`}
                    label={platform.label}
                    checked={draft.platforms.includes(platform.key)}
                    onChange={(on) => change({ platforms: toggled(draft.platforms, platform.key, on) })}
                  />
                ))}
              </div>
            )}
            {shownError("platforms") && (
              <p className="m-0 text-[0.78rem]" style={{ color: "var(--err)" }} role="alert">
                {shownError("platforms")}
              </p>
            )}
          </fieldset>

          <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
            <legend className="mb-1.5 text-[0.8rem] font-medium" style={{ color: "var(--ink-2)" }}>
              Features
            </legend>
            {TIER_FEATURES.map((feature) => (
              <CheckboxRow
                key={feature.key}
                id={`tier-feature-${feature.key}`}
                label={feature.label}
                help={feature.help}
                checked={draft.features.includes(feature.key)}
                onChange={(on) => change({ features: toggled(draft.features, feature.key, on) })}
              />
            ))}
          </fieldset>

          {failure && (
            <p className="m-0 text-[0.8rem]" style={{ color: "var(--err)" }} role="alert" data-testid="tier-error">
              {failure}
            </p>
          )}

          <DialogFooter>
            <button type="button" className="af-btn" onClick={() => onOpenChange(false)}>
              Cancel
            </button>
            <button type="submit" className="af-btn af-btn-primary" disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 size={14} className="animate-spin" />} {tier ? "Save" : "Add tier"}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  id,
  label,
  error,
  help,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[0.8rem] font-medium" style={{ color: "var(--ink-2)" }} htmlFor={id}>
        {label}
      </label>
      {children}
      {error ? (
        <p className="m-0 text-[0.78rem]" style={{ color: "var(--err)" }} role="alert">
          {error}
        </p>
      ) : (
        help && (
          <p className="m-0 text-[0.78rem]" style={{ color: "var(--ink-4)" }}>
            {help}
          </p>
        )
      )}
    </div>
  );
}

function CheckboxRow({
  id,
  label,
  help,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  help?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-start gap-2">
      <Checkbox id={id} checked={checked} onCheckedChange={(state) => onChange(state === true)} className="mt-0.5" />
      <label htmlFor={id} className="text-[0.84rem]" style={{ color: "var(--ink)" }}>
        {label}
        {help && (
          <span className="block text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
            {help}
          </span>
        )}
      </label>
    </div>
  );
}
