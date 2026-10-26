# Agent Add-ons

## Read when

Read before changing what an Organization may request for one Agent, how a Platform Administrator reviews it, how an approved add-on is installed into the pod (the `install-addons` init container, the add-ons volume, the cache), `pending_addons`, the "Add-on install failed" provisioning error, or the Add-ons section and the Platform Add-ons page.

## Role in the system

An **Agent Add-on** is a library or tool installed into one Agent on top of its Runtime: a pinned Python or npm package, a git repository at a commit, a checksummed download, or a reviewed install command. An Organization Owner or Admin requests it for one Agent, saying why. A Platform Administrator approves exactly that request, or rejects it, and may later revoke an approval. An approved add-on is installed the next time the Agent starts.

Add-ons never change the runtime image: the Agent still runs Hermes or OpenClaw, and nothing is built. There are no system-wide installs, no `apt`, and no Dockerfiles. Each add-on belongs to one Agent; nothing is shared between Agents. Why the platform reviews each one, and why that review is a platform write on an Organization's Agent, is in [its ADR](../adr/2026-10-26-platform-administrators-approve-agent-add-ons.md). The epic's delivery state is in [`agent-addons/CHANGELOG.md`](agent-addons/CHANGELOG.md).

## Kinds

Every kind needs a "why" (1–1,000 characters), shown to the reviewer and to the Agent. Each kind's pin is checked (`422` otherwise):

| Kind | Fields | Rule | Installed as |
| --- | --- | --- | --- |
| `pip` | `name`, `version` | A PyPI name without extras; one exact PEP 440 version (a leading `==` is dropped) | `uv pip install --target /opt/addons/python` with the runtime's own Python |
| `npm` | `name`, `version` | An npm name, scoped or not; one exact semver version, no ranges or tags | `npm install --global --prefix /opt/addons/node` |
| `git` | `name`, `url`, `commit` | An `https://` URL without credentials; the full 40-character commit SHA | Fetched and checked out at the commit in `/opt/addons/src/<name>` |
| `binary` | `name`, `url`, `sha256` | An `https://` URL without credentials; the SHA-256 as 64 hex characters | Downloaded to `/opt/addons/bin/<name>`, checked against the SHA-256, made executable |
| `command` | `name`, `command` | Up to 4,000 characters, reviewed verbatim; pinning what it installs is the reviewer's job | Run with `bash -euo pipefail`, in an empty directory, with `ADDONS_DIR=/opt/addons` and `HOME=/opt/addons/home`, so a `curl \| bash` installer works as pasted. Executables it leaves in HOME's usual bin directories are linked into `/opt/addons/bin` (see [installation](#installation)). One that exits 0 having changed nothing in the volume fails |

`name` is a file or directory name for `git`, `binary` and `command` (letters, digits, `.`, `_`, `-`, not starting with a dot). URLs, SHAs and versions are stored as checked, SHAs in lowercase.

**Kinds per runtime.** A kind is offered only where its tool is in the runtime image (`KINDS_BY_RUNTIME`; `400` for one that is not). Both pinned images have `uv`, their own Python, `git`, Node and `npm`, so both offer every kind; the runtime contract tests prove each one in each image. `AgentAddonsRead.available_kinds` is what the request dialog offers.

## States

```text
Pending ──approve──► Approved ──revoke──► Revoked
   │ └──reject (reason)──► Rejected
   └──withdraw──► Withdrawn
```

- **Pending** until a Platform Administrator decides. The Organization may withdraw it only while it is Pending.
- **Approved** is installed at the Agent's next start, and stays until a Platform Administrator revokes it.
- **Rejected** needs a reason, which the Organization sees. **Withdrawn**, **Rejected** and **Revoked** are final.
- A request is never edited. To change one, reject it; the Organization files a new request.
- Any other move is refused (`409`). Repeating the move that already happened is a no-op: it answers `200`, records nothing, and keeps the first decision, its rejection reason included.
- An Agent has at most **20** Pending and Approved add-ons (`409` beyond). Withdrawn, Rejected and Revoked ones do not count.
- One Pending or Approved add-on per kind and name on an Agent, ignoring case (`409`; a partial unique index). The same package may be requested again once the earlier request is no longer active.

## Who does what

- **Organization Owners and Admins** list, request and withdraw, through `agent.addon.manage`. No Agent Access Role grants it, so an Agent's own Owner, Editor or Viewer who is a Member cannot (`403`); an Agent the caller cannot see is `404`. Each route resolves the Agent through `AgentAuthorization.require_action` first, then checks the Organization grant. Withdrawing is open to any of them, not only the requester: the request is the Organization's. `allowed_actions` lists the permission for them; a read-only API key lists but cannot request or withdraw. See the [RBAC brief](rbac/IMPLEMENTATION-BRIEF.md).
- **Platform Administrators** list every request across Organizations and approve, reject or revoke one (`require_platform_admin`, no Membership; a read-only API key cannot decide). They read the request and the names that place it (Organization, Agent, runtime, requester), through a fixed column list (`PlatformAgentAddonRow`), and nothing else of the Agent. A decision never starts or stops the Agent.

## Installation

Approved add-ons are installed at start, in the pod, and cached between starts.

- **When.** `AgentService._provision_and_start` reads the approved add-ons, by approval order, at every start, like the [Agent Size](agent-sizes.md). An approval or revocation never touches a running pod. `agent.running_addons_hash` records the set the pod was built with (`addons_set_digest`; null with none), and stop clears it. `AgentRead.pending_addons` is true while a running Agent's recorded set differs from the approved set now. Any restart applies it, so whoever holds `agent.lifecycle.manage` may.
- **The init container.** `install-addons` runs after `fix-pvc-owner` and before the agent container, on the Agent's own runtime image and Agent Size resources, as the runtime's non-root user (`hermes` 10000, `node` 1000; `runAsNonRoot`, no privilege escalation). It mounts only the add-ons volume, read-write, and its own ConfigMap (`agent-<id>-addons`: the install script and `addons.json`, the approved steps and their hash). It gets no Secret, no LiteLLM key, no integration environment, and not the Agent's main ConfigMap, which carries per-start credentials. The whole step has 10 minutes (`timeout 600`; the script stops itself 20 seconds sooner so it can name what ran out of time). The script is `api/domains/agents/scripts/install-addons.py`.
- **The volume.** A per-Agent PVC, `agent-<id>-addons`, 2Gi, ReadWriteOnce, created at the first start with an approved add-on and kept until the Agent is deleted, mounted at `/opt/addons`. `fix-pvc-owner` hands its top directory to the runtime user. It is separate from the data volume because the Agent can write that one through HOME: add-ons there could be changed by the Agent, would take its 1Gi, and would ride along in Agent Restore Points. Restore points never include it.
- **The cache.** The plan's hash covers the runtime image, the ordered approved add-ons and the install script (`addons_install_hash`). When the volume's marker (`/opt/addons/.agentbarn-addons-hash`) already holds it, the init container exits at once. Otherwise it wipes the volume, installs everything approved in order, and writes the marker last, so a new approval, a revocation, a new runtime image and a new install script all reinstall from scratch, and an install that failed or was cut short is redone on the next start.
- **Command add-ons and HOME.** Every `command` add-on runs with `HOME=/opt/addons/home`, one HOME shared in approval order, so what an installer puts in HOME stays in the volume. After the last add-on, the executables in HOME's `bin`, `.local/bin`, `.*/bin`, `.local/share/*/bin` and `.local/share/solana/install/active_release/bin` are linked into `/opt/addons/bin` by relative links (`link_home_executables`). A name `bin` already has is not replaced, and a name the runtime image already has on its `PATH` (`node`, `python3`, `git`) is not linked, because `bin` comes ahead of the image's `PATH`. The agent container keeps its own HOME, so a tool that needs its install directory at run time (rustup's proxies need `RUSTUP_HOME`), or writes into it (cargo's registry), does not work from the read-only volume; a full toolchain belongs in a runtime image.
- **Python packages and the runtime.** Add-ons are importable from the runtime's own Python through `PYTHONPATH`, ahead of its own packages. So that one cannot shadow a package the runtime depends on at another version, pip add-ons are installed against the runtime's installed versions as constraints (`uv pip freeze` of the runtime's Python): an add-on that needs a different version of one of them fails to install, naming it, instead of breaking the runtime.
- **The agent container** mounts the volume read-only, so the Agent can use add-ons but not change, remove or add to them. It gets `PYTHONPATH=/opt/addons/python`, `NODE_PATH=/opt/addons/node/lib/node_modules` and `AGENTBARN_ADDONS_PATH=/opt/addons/bin:/opt/addons/node/bin`, which `start.sh` puts in front of `PATH` (a pod's `PATH` cannot be set without replacing the image's own), behind the commands Agent Barn manages. `AGENTS.md` gains an **Add-ons** block naming each one, its kind and pin, where it is, and why, and telling the model not to install or change packages itself.
- **Egress.** The install reaches PyPI, npm, GitHub and the download URLs over the pod's open egress (see the [egress ADR](../adr/2026-09-02-credential-gateway-egress-modes.md)). Nothing it fetches is cached outside the Agent's volume.

## When an install fails

If any add-on fails, the start fails. The init container writes `{"addon_id": ..., "reason": "failed" | "timeout" | "checksum"}` to its termination message and exits non-zero. The kubelet would retry it in a crash loop; instead, the next read of the Agent (its page or health) sees the failed init container, keeps the last 80 lines of the install log as a log snapshot, deletes the Deployment, and puts the Agent in `ERROR` with the provisioning error **Add-on install failed** (`ADDON_INSTALL_FAILED`). Its detail names the add-on and why (`humanize: install failed`), from the id matched against the Agent's approved add-ons, never from text the pod wrote. The Agent's page shows the error, and its Logs tab shows the install log. Platform Administrators see neither. Recovery is to start again, if the failure was passing, or to revoke or withdraw the add-on. A `command` that leaves the volume unchanged fails as `install failed` too, and its log says it installed nothing into `$HOME` or `$ADDONS_DIR`: the working directory and `/tmp` are discarded.

## Deleting an Agent

Deletion withdraws its Pending requests, in the deletion's transaction and correlation, with one `agent.addon.withdrawn` each. Approved, Rejected, Withdrawn and Revoked ones stay as history on the soft-deleted Agent, and the Platform Add-ons page marks the Agent deleted. The add-ons volume and ConfigMap are deleted with the Agent's other resources, when it ever had an approved add-on.

## Audit and notifications

Each state change is one Organization-scoped Security Audit Record: `agent.addon.requested`, `.approved`, `.rejected`, `.withdrawn` and `.revoked`. Each carries the request (kind, name, pin, command, why), the state before and after, and on rejection the reason. The actor is the requester's Membership, or for a decision the administrator's Membership when they have one there, else their user. A no-op records nothing. See [domain events](domain-events.md).

`AgentAddonEmailHandler` emails every Platform Administrator about each new request, and the requester about each approval, rejection and revocation. A withdrawal emails nobody. Like the budget emails, each delivery records whom it reached (`agent_addon_email_receipt`), so a retry emails nobody twice.

## API

| Route | Does |
| --- | --- |
| `GET /api/v1/organizations/{id}/agents/{agent_id}/addons` | The Agent's add-ons, newest first, with `available_kinds` and `max_active` (`AgentAddonsRead`) |
| `POST /api/v1/organizations/{id}/agents/{agent_id}/addons` | Request one; the body is one kind's fields and `reason` (`201`, `AgentAddonRead`) |
| `POST /api/v1/organizations/{id}/agents/{agent_id}/addons/{addon_id}/withdraw` | Withdraw a Pending request |
| `GET /api/v1/platform/agent-addons` | Every request, newest first, `PaginatedItems[PlatformAgentAddonRead]`; `state`, `organization_id`, `search` (add-on, Agent or Organization name), `page`, `page_size` (at most 100) |
| `POST /api/v1/platform/agent-addons/{addon_id}/approve` | Approve a Pending request |
| `POST /api/v1/platform/agent-addons/{addon_id}/reject` | Reject a Pending request, `{reason}` |
| `POST /api/v1/platform/agent-addons/{addon_id}/revoke` | Revoke an Approved one |

`AgentRead` carries `pending_addons` and, for Owners and Admins, `agent.addon.manage` in `allowed_actions`.

## UI

- **Agent configuration → Add-ons** (`?section=addons`), shown only with `agent.addon.manage`. It lists each add-on with its kind, state, exact pin, why, who asked and when, and a rejection's reason. **Request add-on** opens a dialog with the kinds the runtime offers and each kind's own fields. Pending ones have **Withdraw**, which asks to confirm. "Pending: applies on restart" shows while `pending_addons` is true, with a Restart button for whoever may restart.
- **Platform → Add-ons** (`/dashboard/platform/agent-addons`, its own rail entry), Pending by default (`?state=`), filterable by state and Organization, searchable. Each request shows its Organization, Agent, runtime, requester, kind, exact pin or command, why, and when it was requested and decided. **Approve**, **Reject** (which needs a reason) and **Revoke** each ask to confirm.

## Source map

| Concern | Source |
| --- | --- |
| Table, kinds and their rules, DTOs, digests | `../../api/domains/agent_addons/models.py` |
| Requests, decisions, the limit, deletion, platform list | `../../api/domains/agent_addons/repository.py` |
| Authorization and errors | `../../api/domains/agent_addons/service.py` |
| Routes | `../../api/domains/agent_addons/routes.py` |
| Emails | `../../api/domains/agent_addons/event_handlers.py`, `../../api/infrastructure/email/templates/agent-addon-template.mjml` |
| Provisioning lookup | `../../api/domains/agent_addons/lookup.py`; `_provision_and_start`, `_observe_addon_install` in `../../api/domains/agents/service.py` |
| Pod spec | `../../api/domains/agents/builders/addons.py`, `build_hermes_deployment`, `build_deployment` |
| Install script | `../../api/domains/agents/scripts/install-addons.py` |
| Install failure | `AgentAddonInstallFailed` in `../../api/domains/agents/provisioning_errors.py`; `get_init_container_failure`, `read_init_container_logs` in `../../api/infrastructure/kubernetes/client.py` |
| Migration | `../../api/migrations/versions/6fe963719ec9_add_agent_addons.py` |
| UI | `../../ui/src/features/agent-addons/`; the `addons` section in `../../ui/src/features/agents/components/agent-configuration-utils.ts`; the rail entry in `../../ui/src/features/navigation/nav-model.ts` |
| Tests | `../../api/tests/integration/test_agent_addons.py`, `test_platform_agent_addons.py`, `test_agent_addons_migration.py`; `../../api/tests/unit/test_agent_addon_builders.py`, `test_install_addons_script.py`; `../../api/runtime_tests/addons_contract.py` (both images); `../../ui/tests/e2e/agent-addons.spec.ts`, `platform-agent-addons.spec.ts` |

## Change impact

- A new kind is a request model, a `KINDS_BY_RUNTIME` entry, an install step in the script, a line in the `AGENTS.md` block, a dialog field set, and a runtime contract in both images.
- Dropping a tool from a runtime image means dropping its kind here first.
- Anything given to `install-addons` beyond its two mounts and `ADDONS_DIR` is a security decision: its whole point is that install code finds no credential.
- A new `Agent` column moves the runtime configuration digest once. The add-on set does not move it: `pending_addons` is the signal.
- A new field on the Platform list is a data-classification decision under the oversight ADR and this feature's ADR: add it to `PlatformAgentAddonRow` deliberately.
