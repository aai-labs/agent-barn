import { formatModelName } from "../utils";

/**
 * Says what a restart would switch this Agent onto.
 *
 * Only rendered when a running pod started on a different model than the one that
 * resolves now — normally because the Organization changed its default underneath an
 * inheriting Agent. The runtime reads its model once at container start, so until
 * someone restarts it the Agent really is still serving the old one; naming the new
 * value here keeps the primary display honest about the present.
 */
export function PendingModelNote({ pendingModel }: { pendingModel: string }) {
  if (!pendingModel) return null;
  return (
    <div className="mt-0.5 text-[0.72rem]" style={{ color: "var(--ink-4)" }}>
      Pending switch to <span className="font-mono">{formatModelName(pendingModel)}</span> on restart
    </div>
  );
}
