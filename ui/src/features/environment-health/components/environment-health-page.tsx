"use client";

import { CircleAlert, CircleCheck, CircleHelp, RefreshCw, TriangleAlert } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { Skeleton } from "@/components/ui/skeleton";

import { useEnvironmentHealth } from "../hooks/use-environment-health";
import type { EnvironmentHealth, EnvironmentSource, SourceState } from "../schemas";
import { formatTime, healthTone, SOURCE_LABELS, SOURCE_STATE_TEXT, TONE_COLOR } from "../utils";
import { AgentProblemsPanel } from "./agent-problems-panel";
import { CapacityPanel } from "./capacity-panel";
import { EventsPanel } from "./events-panel";
import { ServicesPanel } from "./services-panel";
import { VolumesPanel } from "./volumes-panel";
import { WorkloadsPanel } from "./workloads-panel";

const TWO_COLUMNS = { gridTemplateColumns: "repeat(auto-fit, minmax(min(420px, 100%), 1fr))" };

const LEVEL_COPY: Record<EnvironmentHealth["level"], { title: string; body: string }> = {
  ok: { title: "Everything is running", body: "Platform services are up and the namespace has room for new agents." },
  warning: { title: "Something needs a look", body: "The platform is running, but some parts below need attention." },
  critical: {
    title: "The environment needs attention now",
    body: "A platform service is down, the namespace is nearly full, or a critical alert is firing. New agents may fail to start.",
  },
  unknown: {
    title: "The environment's state is unknown",
    body: "Neither pods nor Deployments could be read, so there is nothing to judge the environment by.",
  },
};

const LEVEL_ICON = { ok: CircleCheck, warning: TriangleAlert, critical: CircleAlert, unknown: CircleHelp };

/**
 * The health and capacity of the namespace the platform runs in, for Platform Administrators.
 *
 * Read-only. It reads the Platform's own endpoint, which reads the cluster with the API's
 * service account and carries no cluster text; see the ADR on environment health as Platform
 * Oversight Data. A part the account may not read says so instead of disappearing.
 */
export function EnvironmentHealthPage() {
  const { health, isLoadingHealth, isFetching, error, refetch } = useEnvironmentHealth();

  return (
    <div data-testid="environment-health-page">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="m-0 mb-1 text-[28px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            Environment Health
          </h1>
          <p className="m-0 text-[14px]" style={{ color: "var(--ink-3)" }}>
            Platform services, capacity, failing workloads and cluster warnings
            {health && (
              <>
                {" "}
                in <code className="text-[13px]">{health.namespace}</code>
              </>
            )}
            .
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {health && (
            <span className="text-[12.5px]" style={{ color: "var(--ink-4)" }} data-testid="environment-observed-at">
              Updated {formatTime(health.observedAt)}
            </span>
          )}
          <button className="af-btn flex-shrink-0" onClick={() => void refetch()} disabled={isFetching}>
            <RefreshCw size={14} className={isFetching ? "animate-spin" : undefined} /> Refresh
          </button>
        </div>
      </div>

      {error ? (
        <AppErrorState
          error={error}
          title="We couldn't load environment health"
          description="The environment's health is unavailable right now."
          onRetry={() => {
            void refetch();
          }}
          retryLabel="Retry"
          className="min-h-[15rem] p-0"
        />
      ) : isLoadingHealth ? (
        <HealthSkeleton />
      ) : (
        health && <HealthBody health={health} />
      )}
    </div>
  );
}

function HealthBody({ health }: { health: EnvironmentHealth }) {
  const states = Object.fromEntries(health.sources.map((row) => [row.source, row.state])) as Partial<
    Record<EnvironmentSource, SourceState>
  >;
  // A Deployment or StatefulSet read either way leaves the list of services worth showing.
  const workloadsState =
    states.deployments === "available" || states.stateful_sets === "available" ? "available" : states.deployments;

  return (
    <>
      <LevelBanner level={health.level} />
      <SourcesNotice sources={health.sources} />
      <CapacityPanel lines={health.capacity} ceilings={health.ceilings} quotaState={states.resource_quotas} />
      <div className="grid gap-x-6" style={TWO_COLUMNS}>
        <ServicesPanel
          services={health.services}
          alerts={health.alerts}
          workloadsState={workloadsState}
          monitoringState={states.prometheus}
        />
        <AgentProblemsPanel
          failed={health.failedAgents}
          unhealthy={health.unhealthyRuntimes}
          monitoringState={states.prometheus}
        />
      </div>
      <WorkloadsPanel workloads={health.workloads} podsState={states.pods} />
      <div className="grid gap-x-6" style={TWO_COLUMNS}>
        <VolumesPanel volumes={health.volumes} state={states.volume_claims} />
        <EventsPanel events={health.events} state={states.events} />
      </div>
    </>
  );
}

function LevelBanner({ level }: { level: EnvironmentHealth["level"] }) {
  const tone = healthTone(level);
  const Icon = LEVEL_ICON[level];
  const copy = LEVEL_COPY[level];
  return (
    <div
      className="af-card mb-4 flex items-start gap-3 p-4"
      role="status"
      style={{ borderColor: tone === "muted" ? undefined : TONE_COLOR[tone] }}
      data-testid="environment-level"
      data-level={level}
    >
      <Icon size={20} className="mt-0.5 flex-shrink-0" style={{ color: TONE_COLOR[tone] }} />
      <div className="min-w-0">
        <p className="m-0 text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
          {copy.title}
        </p>
        <p className="m-0 mt-1 text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          {copy.body}
        </p>
      </div>
    </div>
  );
}

/** One line for the sources that could not be read, so a missing part is never mistaken for "all clear". */
function SourcesNotice({ sources }: { sources: EnvironmentHealth["sources"] }) {
  const missing = sources.filter((row) => row.state !== "available");
  if (missing.length === 0) return null;
  return (
    <div className="mb-6 text-[12.5px] leading-relaxed" style={{ color: "var(--ink-4)" }} data-testid="environment-sources">
      Some parts aren&apos;t shown:{" "}
      {missing.map((row, index) => (
        <span key={row.source} data-testid={`source-${row.source}`} data-state={row.state}>
          {index > 0 && "; "}
          {SOURCE_LABELS[row.source]} {SOURCE_STATE_TEXT[row.state as Exclude<SourceState, "available">]}
        </span>
      ))}
      .
    </div>
  );
}

function HealthSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      <Skeleton className="h-[76px] w-full rounded-xl" />
      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(200px, 100%), 1fr))" }}>
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-[98px] rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-[220px] w-full rounded-xl" />
    </div>
  );
}
