# Shared SSH access — execution evidence

Observed: 2026-11-16 (Europe/Berlin)
Tested implementation: `ee7e5a9c81b8c73cda9f731a35eb06cf6fddd261`, based on staging `d39a4b43`.
The following evidence/documentation commit changes no executable source.

## Environment and boundary

A local Agent Barn product API and Next.js UI ran with a dedicated PostgreSQL 18
database and Redis instance. The only Agent was **SSH Demo Agent (mock)** in
**SSH Test Barn**, configured as Hermes. Kubernetes resource creation and LiteLLM
provisioning used the repository's test adapters. A real Hermes container ran the
generated relay and native `terminal_tool`; a separate real signing listener used
verified TLS, the real database and OpenSSH. Disposable Debian SSH servers accepted
only the generated public key. No production credentials or paid model calls were used.

The Agent's read-only configuration bind mount contained only the relay, public
profiles and public CA certificate. Its socket directory was owned by `hermes`
with mode 0700 and its socket mode was 0600. The Hermes image also creates its
ordinary empty `/opt/data` volume; it was not a private-key mount.

The production Kubernetes scheduler, actual model turn loop, external providers,
production ingress and cluster NetworkPolicy enforcement were not exercised by
this mock demo. The separate runtime contracts execute both generated volume-owner
init commands in the actual images before checking native terminal use.

## Acceptance criteria and proof

| Criterion | Observed proof |
| --- | --- |
| Ordinary SSH, Git and file transfers work without delivering the private key to the Agent. | [Native terminal transcript and public mounts](evidence/live-demo.json): SSH returned `ssh-demo-connected` and `root`; Git clone/commit/push/fetch succeeded; scp/sftp returned the original `ssh-demo-file`. Both runtime contracts passed. |
| Administrators can generate/import keys and receive only public metadata. | Real browser generation and deletion succeeded against the live API; [API request/response evidence](evidence/live-demo.json) contains no private material. `test_import_encrypted_key_duplicate_key_and_safe_validation` and generation tests passed. |
| Access is scoped by Organization and Agent authority. | Real Member login could inspect the public key but had no create/save controls ([UI states](evidence/ui-states.json)). API role cases covered Owner, Editor, Viewer and concealed/unassigned Agents, plus cross-tenant foreign keys. |
| Restricted signing refuses unapproved host identities, wrong accounts, forwarding and keyring mutation. | The second disposable server accepted the same public user key but had a different host identity; authentication failed even with client host checking bypassed ([transcript](evidence/live-demo.json)). Wrong-user, forged-binding, forwarding, mutation and malformed-frame API cases passed against real OpenSSH. |
| Revocation and restart generations change future authentication authority. | Disabling the key caused a fresh native SSH command to fail; re-enabling and Apply & Restart issued a new generation that returned `fresh-generation-connected`. Generation replacement and remove/re-add regression tests passed. |
| Signing audit is durable and failure prevents release of a signature. | [Audit projection evidence](evidence/audit-projection.json): reconciliation published 34 deliveries to the dedicated Redis; direct execution of the real delivery processor completed 26 SSH projections, including eight authorized and eight issued signing records. Both pre-sign and result-audit failure cases refused the connection. |
| The UI supports loading, empty, failure/retry and permission states without breaking adjacent integrations. | [Live UI state checks](evidence/ui-states.json): a held real request displayed loading, unmatched real search displayed empty, controlled HTTP 503 displayed Retry, and Retry recovered real data. The adjacent empty provider-integration section loaded. 29 selected browser checks passed. |
| Deployment remains opt-in and the schema and runtime setup are compatible. | Enabled/disabled Helm renders and migration checks passed; downgrade preserved keys until explicit deletion. Both runtime images executed the generated init argv successfully and produced the expected ownership/0700 permissions. |

## User-facing flow

1. Sign in through `/login` using the local Organization Owner fixture.
2. Open **Settings → Shared Credentials**. Inspect the disposable key and its
   specific-server policy. Add a generated key, verify the public identity, and
   delete that unattached key through the confirmation dialog.
3. Open **SSH Demo Agent (mock) → Configuration → Integrations**. Verify its
   assigned SSH key and generated `ssh ab-<key-id>-demo` shortcut.
4. Run the native terminal commands preserved in [live-demo.json](evidence/live-demo.json).
5. Change the destination to the unapproved host fixture while bypassing client
   host checking: authentication still fails at the signer boundary.
6. Disable the shared key through `PUT /ssh-credentials/{id}`: a fresh command
   fails. Re-enable, Apply & Restart, and verify a fresh generation succeeds.
7. Sign in as the local Member fixture and verify that inspection is read-only.

The successful UI pass used real password authentication and the actual HTTP API,
with no fabricated browser API data. The loading/outage checks separately held
one request or supplied controlled HTTP 503 responses; those controlled failures
are not claims that the real API returned 503.

## Screenshots

[Shared Credentials](evidence/shared-credentials.png),
[public identity and server policy](evidence/key-policy.png),
[Agent SSH access](evidence/agent-access.png).

![Shared SSH credentials in the running local app](evidence/shared-credentials.png)

![SSH key attached to the mock Agent](evidence/agent-access.png)

## Automated verification at the tested commit

```bash
make check-api
make check-ui
make lint-ui
make check-ssh
make check-migrations
git diff --check
```

All passed. Compose and changed GitHub workflow YAML also parsed successfully.
API and both runtime Docker images built successfully from this source tree.

```bash
PYTEST_XDIST_AUTO_NUM_WORKERS=4 \
REDIS_URL=redis://127.0.0.1:1/0 \
PYTEST_ADDOPTS='-k "ssh or credential_gateway or shared_credential or custom_api or test_agents or openrouter_client or domain_events or agent_runtime_digest or restore_point_builders or restore_point_manifest" --tb=short' \
make test-api
```

632 selected API/unit/integration checks passed. This is a regression selection,
not a claim that the complete API suite ran. The deliberately unavailable Redis
address isolates these tests from unrelated host services; durable outbox writes
use real per-worker PostgreSQL databases. Real Redis delivery was verified
separately in the local demo described above.

```bash
HERMES_TEST_IMAGE=agentbarn-hermes-base:ssh-pr \
OPENCLAW_TEST_IMAGE=agentbarn-openclaw-base:ssh-pr \
REDIS_URL=redis://127.0.0.1:1/0 \
PYTEST_ADDOPTS='--tb=short --show-capture=no -q' make test-ssh-runtime

(cd ui && pnpm exec playwright test \
  tests/e2e/ssh.spec.ts tests/e2e/shared-credentials.spec.ts \
  tests/e2e/integration-isolation.spec.ts tests/e2e/integration-setup.spec.ts)
```

Both runtime contracts and all 29 selected browser checks passed. The automated
browser suite uses mocked APIs; the manual screenshots and UI checks above use
the running API. Existing dependency deprecation warnings were non-fatal.

## Review limits and delivery

The ADR and current contracts live in [Shared SSH access](../ssh-access.md) and
its linked documents; this file records observations only. Rollout order and
rollback are in [operations](../../guidelines/operations.md#ssh-signing-deployment).
The feature defaults off. The chart is 0.20.0; compatible runtime versions start
at Hermes 0.2.12 and OpenClaw 0.7.9. Migration `a193d7f0c284` follows staging head
`38de1199ae19`; no existing provider credentials are converted.

Cluster-level ingress/network enforcement and paid provider/model execution are
unverified here. The audit processor was invoked directly after real broker
publication; background worker scheduling itself was not part of this manual
check. No recording SSH gateway or command-level policy is claimed. Existing
remote sessions survive revocation, and authentication audit is not a complete
remote command log. An epic change log is N/A: this is one implementation PR.
