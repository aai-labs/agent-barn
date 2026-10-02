"use client";

import { Muted, PANEL_GRID_STYLE, Panel, PanelSkeleton, StatusFacts, UsageFacts } from "./agent-detail-panels";
import { usePlatformAgentDetails } from "../hooks/use-platform-agent-details";

/**
 * What an opened Heaviest agents row shows: the same Status and Resource usage panels the
 * Organization Usage page draws, from the Platform's own endpoint.
 *
 * No Cost panel, and no links: a Platform Administrator has no Membership, so an
 * Organization's agent pages are not theirs to open. Mounted only while the row is open.
 */
export function PlatformAgentDetails({ agentId }: { agentId: string }) {
  const { details, isLoadingDetails, error } = usePlatformAgentDetails(agentId);
  const failed = !!error || (!isLoadingDetails && !details);

  return (
    <div className="grid gap-4 p-4" style={PANEL_GRID_STYLE} data-testid="platform-agent-details">
      <Panel title="Status" testId="platform-agent-status">
        {isLoadingDetails ? (
          <PanelSkeleton />
        ) : failed || !details ? (
          <Muted>Status couldn&apos;t be loaded.</Muted>
        ) : (
          <StatusFacts
            status={details.status}
            health={details.healthStatus ? { status: details.healthStatus } : null}
            canReadHealth
            lastErrorSummary={details.lastErrorSummary}
            effectiveModel={details.effectiveModel}
            agentType={details.agentType}
            createdAt={details.createdAt}
            restartCount={details.restartCount}
            terminationReason={details.terminationReason}
          />
        )}
      </Panel>
      <Panel title="Resource usage" testId="platform-agent-usage">
        <UsageFacts
          canRead
          stopped={details?.status === "STOPPED"}
          isLoading={isLoadingDetails}
          failed={failed}
          usage={details?.resourceUsage ?? null}
        />
      </Panel>
    </div>
  );
}
