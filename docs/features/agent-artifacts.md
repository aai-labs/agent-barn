# Agent artifacts and file sharing

Status: AF-415 implementation on AF-389; not deployed. [AF-415 specification](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3089039363) and [AF-387 delivery log](agent-workflows/CHANGELOG.md).

## Ownership and access

One shared `artifacts` domain serves ordinary Agent sessions and workflow steps
on Hermes and OpenClaw. PostgreSQL owns metadata and reference identity; private
S3-compatible storage owns bytes. Garage is the selected deployment target.
An artifact belongs to exactly one Organization and Agent. Workflow, run, step,
attempt and generation provenance are optional and server derived. Keys have the
fixed form `artifacts/<organization UUID>/<agent UUID>/<artifact UUID>` and never
include user filenames. Replacement always creates a new artifact ID.

Human metadata/list/download-link reads require current Membership, `agent.read`
and the scoped undeleted Agent under the [RBAC brief](rbac/IMPLEMENTATION-BRIEF.md).
Human staging, publication and deletion require `agent.update`; read-only Personal
API Keys cannot mutate. Agent General Access and custom roles use the existing
policy. Cross-tenant, wrong-Agent and inaccessible resources return 404; missing
write authority on a visible resource returns 403. No artifact-specific roles or
cross-Agent sharing grants are introduced.

Runtime requests use a purpose-separated HMAC capability derived from the
Agent's existing per-start ingest secret. The credential contains the Agent UUID;
the service verifies it against the persisted encrypted secret and a running,
undeleted Agent. It rotates on restart and stops resolving when the Agent stops.
The API derives Organization/Agent identity; callers cannot supply another bucket
or object key. Agents receive no S3 credentials. Ordinary chat publication needs
no workflow. Workflow publication additionally requires the current attempt
capability, run generation/state/deadline, owning Agent and current initiating
Membership authority. Those fences are checked before storage and again before
READY, while holding the run/publication locks. Agent-scoped tools remain available
in ordinary sessions; supplying workflow provenance always requires its capability.

## Publication and immutable handoff

1. `POST /organizations/{organization_id}/agents/{agent_id}/artifacts` stages
   filename, content type, byte size and lowercase SHA-256, returning UPLOADING.
2. `PUT .../artifacts/{artifact_id}/content` accepts bounded raw bytes. The API
   computes size and SHA-256, writes only matching content, then reads it back
   from S3 and verifies it before committing READY. The service serializes
   finalization and purge on the same metadata row; READY objects never re-enter
   the byte writer. Garage 2.4.1 ignores conditional Put headers, so immutability
   is enforced by this transaction and the fixed size/checksum, not by an S3
   conditional-write or object-lock promise. Bucket credentials remain service-only.
3. Exact duplicate finalization returns the same READY identity; changed bytes
   cannot replace it. After a failed/uncertain upload, stage a new ID to retry.
   A crash after S3 write leaves UPLOADING metadata for cleanup; it is never
   exposed as a file. Staging expires after one hour. Interrupted/oversized
   request bodies remain unavailable and expire through the same cleanup path.

The default file limit is 25 MiB, configurable from 1 byte to 100 MiB. Uploads
are buffered within that bound; choose API concurrency/memory limits accordingly.
Display filenames are at most 255 characters and cannot contain paths or control
characters. Content types are bounded MIME identifiers. All downloads use
attachment disposition and octet-stream; active content has no inline preview.

Both runtimes receive `/usr/local/bin/agentbarn-artifacts` in their generated
ConfigMap and executable mount. `upload <workspace-file>`, `list [--page N]`,
`retrieve <id> <new-path>` and `link <id> [--seconds N]` use the same scoped service.
Upload roots are `/workspace` on Hermes and
`/home/node/.openclaw/workspace` on OpenClaw. Retrieval verifies the expected
checksum and refuses to overwrite a destination. Workflow prompts provide
`--attempt-id` and `--attempt-token` for publication. Tokens must not enter logs.

Publication pins an exact artifact ID/checksum to its active run. Completion
records published files in the step checkpoint, so later sessions receive immutable
references alongside earlier text summaries. Workspace paths and signed URLs are
never reference identities. Trusted services can acquire checksum-validated pins
through `artifacts.references.pin` and release them transactionally; this is the
integration seam for future reviews, not an approval implementation. Checkpoint
and review owners release their own pins; the run-repair scan never interprets
their owner UUIDs as run IDs.

## Downloads and ordinary messaging

`GET .../artifacts` supports server-side pagination and optional run/step filters.
`GET .../artifacts/{id}` reads READY metadata;
`GET .../artifacts/{id}/download-link` issues a fresh S3 bearer URL after current
access checks. The default lifetime is 900 seconds. Requests may choose a shorter
lifetime up to the configured maximum (default 3,600 seconds, bounded at 86,400).
URL expiry does not delete bytes or expire an approval. Anyone holding an issued
URL can download until expiry; revocation prevents new issuance and does not
promise immediate revocation of existing URLs. Object deletion may make links
unavailable sooner.

The Agent Files view shows READY chat, human and workflow files with names,
sizes, types, provenance and download actions. Run/step attachments use the same
service alongside existing text summaries. Each click requests a fresh link;
access errors conceal protected responses and display a retryable failure.
Query identity includes Organization, Agent, run, step and pagination.

CLI publication returns actual identity/checksum and a signed URL. The Agent may
share it using existing native messaging tools under its configured policy.
Publication/link creation does not authorize or perform an external send. Workflow
steps remain sessions inside the existing owning Agent with its current tools,
Integrations, approval policy and spend limits.

## Retention, deletion and recovery

Ordinary unpinned files retain for 30 days from publication. Active run/checkpoint
or future pending-review references prevent expiry. Settlement releases run pins
in the same transaction and starts 30 days from final active reference release.
Paused/blocked runs remain pinned. Cancellation retains published outputs and
releases pins on settlement. This is independent of the workflow's 90-day
content-bearing text/history retention and future approval lifetimes.

Deletion refuses an actively pinned artifact. Authorized deletion conceals it by
marking DELETING; actual S3 deletion is asynchronous. Agent soft deletion
immediately conceals all files through scoped queries. Owner and provenance IDs
intentionally have no cascading FKs: hard deletion cannot erase the S3 cleanup
journal. The operator-only bounded purge detects deleted/missing owners,
expired unpinned files, stale uploads and prior deletion failures. It repairs
run references whose run was removed, and locks/validates the exact stored bucket and
canonical tenant key before deleting. Failures retain DELETING evidence, increment
attempt count and use bounded exponential retry delay. Concurrent publication
and purge serialize; DELETED tombstones retain identity without file bytes.

Storage disabled or unavailable returns truthful artifact errors without blocking
chat or text-only workflow results. Failed uploads are never READY. See
[operations](../guidelines/operations.md#agent-artifact-storage-garage) for setup,
migrations, rollback and recovery. [Evidence](agent-artifacts/EVIDENCE.md) separates
local real-storage/runtime contracts from unperformed live deployment acceptance.
