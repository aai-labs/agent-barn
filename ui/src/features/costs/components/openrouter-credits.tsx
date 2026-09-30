"use client";

import { CircleAlert, TriangleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import { formatSpend } from "../format";
import type { PlatformCostSummary } from "../schemas";
import { StatCard } from "./cost-summary-cards";

// Matches the OpenRouterCreditsLow alert in helm/monitoring/values.yaml, so the page
// and the pager cannot disagree about what "low" means.
export const CREDITS_LOW_USD = 5;

type Credits = Pick<
  PlatformCostSummary,
  "creditsStatus" | "creditsRemaining" | "creditsLimit"
>;

export function isCreditsLow(summary: Credits): boolean {
  return (
    summary.creditsStatus === "ok" &&
    summary.creditsRemaining !== null &&
    summary.creditsRemaining < CREDITS_LOW_USD
  );
}

export function OpenRouterCreditsCard({ summary }: { summary: Credits }) {
  if (summary.creditsStatus === "no_limit") {
    return (
      <StatCard
        label="OpenRouter credits"
        value="No limit"
        hint="the key has no credit limit set"
        testId="cost-credits"
      />
    );
  }

  if (summary.creditsStatus === "unavailable" || summary.creditsRemaining === null) {
    return (
      <StatCard
        label="OpenRouter credits"
        value="Unavailable"
        hint="the balance could not be read"
        testId="cost-credits"
      />
    );
  }

  return (
    <StatCard
      label="OpenRouter credits"
      value={formatSpend(summary.creditsRemaining)}
      hint={
        summary.creditsLimit === null
          ? "remaining on the key"
          : `of the key's ${formatSpend(summary.creditsLimit)} limit`
      }
      testId="cost-credits"
    />
  );
}

export function OpenRouterCreditsWarning({ summary }: { summary: Credits }) {
  if (isCreditsLow(summary)) {
    const spentOut = summary.creditsRemaining === 0;
    return (
      <Alert
        variant="destructive"
        className="mb-6 items-start border-destructive/30 bg-destructive/5 px-4 py-3"
        data-testid="cost-credits-warning"
      >
        <CircleAlert aria-hidden />
        <AlertTitle>
          {spentOut
            ? "The OpenRouter key has reached its spending limit"
            : "The OpenRouter key is close to its spending limit"}
        </AlertTitle>
        <AlertDescription>
          <span className="block">
            {formatSpend(summary.creditsRemaining ?? 0)} left
            {summary.creditsLimit !== null &&
              ` of the key's ${formatSpend(summary.creditsLimit)} limit`}
            .{" "}
            {spentOut
              ? "Agents cannot make model calls until the key's limit is raised, or until it resets if a reset period is set. This is the key's own cap: adding credit to the account does not lift it."
              : "Agents stop making model calls when it reaches zero."}
          </span>
          <a
            href="https://openrouter.ai/settings/keys"
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-block font-medium text-destructive underline underline-offset-3"
          >
            Open key settings on OpenRouter
          </a>
        </AlertDescription>
      </Alert>
    );
  }

  if (summary.creditsStatus === "unavailable") {
    return (
      <Alert
        className="mb-6 items-start px-4 py-3"
        data-testid="cost-credits-warning"
      >
        <TriangleAlert aria-hidden />
        <AlertTitle>OpenRouter credits could not be read</AlertTitle>
        <AlertDescription>
          The balance shown on this page is unknown, not healthy. Check that
          OPENROUTER_API_KEY is set and valid on the API.
        </AlertDescription>
      </Alert>
    );
  }

  return null;
}
