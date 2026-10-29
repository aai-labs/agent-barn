# Task Tracker Backend: Spike Findings

**Date:** 2026-10-20
**Author:** Ananiya
**Scope:** Whether an existing self-hosted tracker can be the headless backend for MDP-45 ("Centralized task tracking plus UI"): Agents open a task for any non-trivial Request, and users track progress and find the files the Agent produced.
**Status:** Spike complete. Vikunja was not adopted: tasks are a native store, see [`../../adr/2026-10-21-native-agent-task-store.md`](../../adr/2026-10-21-native-agent-task-store.md).
**Evidence:** the PASS/FAIL results below came from a throwaway local harness (Docker Compose and k3d stacks with an API walk-through script), which is not kept in the repository.

---

## Summary

Of Vikunja, Kanboard and Forgejo, only **Vikunja v2.7.0** fits a headless backend. Every flow MDP-45 needs passed against it in Docker and in local k3d: scoped service token, one project per Organization with a child project per Agent, task status, comments, attachments, cross-project filtered listing, signed webhooks, and a delete that cascades to tasks and stored files. It also passed with S3 attachment storage. It needs one Go container (~100 MiB RSS) and a Postgres.

Using a tracker headless does not remove the integration work. Agents cannot hold tracker credentials, because every pod in the namespace can reach every in-namespace service, so our API stays the only client. Our API also keeps the Organization/Agent → project mapping and enforces RBAC itself.

## Constraints the backend must meet

- **Namespace-only.** It must run inside our tenant namespace with no cluster-scoped resources, as our existing charts do (Deployment, StatefulSet, Service, Secret, ConfigMap, Job).
- **No direct Agent access.** Agent pods share the namespace and nothing isolates them at the network level. Agents reach tasks only through Ingest endpoints, authenticated by their per-Agent ingest key. The tracker credential stays in the API.
- **Tenancy belongs to us.** Visibility follows `AgentAuthorization` and `agent_scope_predicates`. The tracker sees a single service identity.
- **Files must survive the Agent.** Attachments are uploaded off the Agent's ReadWriteOnce workspace volume, so they stay downloadable after the Agent stops or is deleted.

## Hands-on results: Vikunja v2.7.0

Run against `vikunja/vikunja:latest` (reports `v2.7.0`) with Postgres 16. Three setups: Docker with local file storage, Docker with S3 storage (SeaweedFS), and local k3d.

| Flow | Result | Notes |
|---|---|---|
| Service user with registration disabled | PASS | `vikunja user create` CLI. The admin users API needs the paid `admin_panel` feature, so bootstrap uses the CLI. |
| Scoped API token created over the API | PASS | `PUT /tokens` with per-route-group permissions and a required `expires_at`. A call outside the scopes (`/teams`) returns 401. |
| Organization project → Agent child project | PASS | `parent_project_id`. |
| Create task, move to "Doing", mark done | PASS | New kanban views come with To-Do / Doing / Done buckets, which map onto our statuses. |
| Comment on a task | PASS | |
| Upload, list and download an attachment | PASS | Multipart upload. The bytes round-trip exactly and the MIME type is kept. |
| Oversize upload (21 MB against the 20 MB default) | PASS, with a quirk | Rejected, but with **HTTP 200** and an `errors` array in the body. Our client must check `errors`, not only the status code. |
| List tasks across Agent projects with filters | PASS | `GET /tasks?filter=project in a,b && done = false`, paginated (50 per page by default). |
| Filter by parent (Organization) project | Not inherited | A parent filter does not return child-project tasks. We pass explicit project IDs, which RBAC needs anyway. |
| Project webhook with secret | PASS | HMAC-SHA256 in `X-Vikunja-Signature`. No retry on failed delivery. |
| Delete Agent project | PASS | Tasks return 404, and the file is gone from both local disk and the S3 bucket. |
| Runs in local k3d | PASS | StatefulSet with a `volumeClaimTemplate`, `runAsNonRoot`, `fsGroup: 1000`, no ServiceAccount token, no cluster-scoped resources. Same flow results. |
| Footprint | measured | Vikunja 97 MiB, Postgres 46 MiB idle. Image is 170 MB. |

From the v2.7.0 source and docs, not exercised in the spike:

- **Licence and model:** AGPL-3.0-or-later, open-core. Pro features (admin panel, audit logs, time tracking, user invites) need a key. Nothing we need is behind it.
- **Services:** no required services besides the database. Redis and mail are optional, and Typesense was removed in 2026.
- **Bot users** (`PUT /user/bots`) can own tokens, so the service identity does not need to be a human-style account.
- **Hard delete only:** deleting a project recurses through every child project, with no trash or undo.
- **Release cadence:** about one minor release a month, plus two major releases in 2026 (v1.0 in January, v2.0 in February). Migrations run automatically at start-up.
- **Replicas:** plan for one. Several replicas would need Redis and S3, and cron jobs have no distributed lock.

## Rejected: Kanboard

Kanboard is MIT licensed, active as v1.2.54 (2026-08-29), and light. It fails the constraints:

- **No tenancy boundary.** The application token bypasses project permissions entirely.
- **No cross-project search and no pagination.** `searchTasks` is scoped to a single project, and the list calls return everything.
- **Weak file handling.** Files travel as base64 inside JSON-RPC, which the docs advise against for large files. Storage is local disk only, and the S3 plugin was archived in 2019.
- **Weak webhooks.** One instance-wide URL, a token in the query string, no signing, and the receiver must answer within 1 second.
- **Security history.** Nine security advisories in 2026, including path traversal through the task-file upload API (fixed in 1.2.47).
- **No new features** ("maintenance mode").

## Rejected: Forgejo

Forgejo v17.0.0 / v15.0.10 LTS is GPL-3.0-or-later. It has a mature issue API, signed webhooks, scoped tokens with `Sudo`, and attachments on local or MinIO storage. It is the wrong shape:

- **Issues must live in a git repository,** so the model becomes Organization → repo → issues, and most of the product (git, SSH, packages) is surface we would have to switch off.
- **Project boards are not in the API.** Statuses would have to be rebuilt from labels.
- **Org deletion fails while the org owns repos,** and failures removing files from storage are only logged.
- **The chart says it is not HA-ready.**

## Not taken forward from the earlier scan

- **Plane:** too heavy to run unseen (Django, Celery, Valkey, RabbitMQ, object storage and several frontends).
- **Taiga:** Django, RabbitMQ and an events server.
- **WeKan:** needs MongoDB.
- **Planka:** reportedly under a custom non-OSI licence since v2.
- **Focalboard:** unmaintained.

## Other findings

- **MinIO images cannot be pulled.** Neither `minio/minio` nor `quay.io/minio/minio` could be pulled, latest or pinned. Any plan that says "MinIO for object storage", ours included, needs another S3 provider. Options: a managed bucket (the cluster runs on Hetzner, which offers Object Storage) or another S3-compatible server. SeaweedFS worked for the spike.
- **The tracker does not remove our integration work.** Even with Vikunja, the platform still needs:
  - the Ingest endpoints for Agents;
  - the user routes with RBAC;
  - a table mapping Organization/Agent to project and task IDs;
  - consistency between our database and Vikunja on create and delete;
  - the bundled skill and runtime policy for both runtimes;
  - the UI.

  Vikunja replaces the task tables, attachment storage, kanban state and webhooks.

## Open questions for the decision

1. **Legal:** is running unmodified AGPL software behind our API acceptable? A fork would also bring the AGPL's network-use clause into play.
2. **Object storage:** which S3 provider should hold attachments in production? Local volume on a single-replica StatefulSet is the fallback.
3. **Upgrades:** do we pin minor versions and own the upgrade cadence, given two major releases this year?
