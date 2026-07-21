# Development and operations

## Install dependencies

From the repository root:

```bash
cd api && uv sync
cd ../ui && pnpm install
```

API configuration is read from the repository root `.env`; tests may use `.env.spec`.

## Local development

```bash
make db-up       # PostgreSQL only
make dev-api     # product API on :8000
make dev-ui      # UI on :3000
make up          # full Docker stack, including the separately served Ingest app
make down
make restart
make logs
make clean       # remove stack volumes and orphans
```

Use `make db-down`, `make db-logs`, and `make db-restart` for database lifecycle. Prefer repository Make targets over ad hoc equivalents.

## Database migrations

```bash
make migrate
make rollback
make makemigrations
```

Schema changes require a migration under `../../api/migrations/versions/`. Review generated migrations before applying them. Production deployment runs Alembic through the API chart migration hook described in `../architecture/runtime-and-deployment.md`.

## Checks and tests

Testing and verification commands live in `testing.md`. Run the smallest complete set for the touched area before widening to full suites.

## Deployment shape

The deployable services have independent Helm charts. `../../helmfile.yaml.gotmpl` controls release ordering, and `../../.github/workflows/deploy.yml` builds images and applies Helmfile. Read `../architecture/runtime-and-deployment.md` before changing runtime images, agent Kubernetes resources, chart wiring, migrations, or deployment order.

## Versioning and releases

Each deployable chart has independent versions in `Chart.yaml`:

- `appVersion` is the immutable image tag built and deployed for that service. Bump it whenever that service's image content changes: minor for features, patch for fixes.
- Chart `version` is the packaging version. Bump it when chart templates or values change, independently of application code.

Rules:

- API and UI versions are independent; bump only the service that changed.
- Never reuse an `appVersion` for different image content.
- Bump versions late, ideally immediately before the PR, to reduce merge conflicts.
- The git commit or PR is the product release identifier; there is no shared API/UI release number.
- `../../.github/workflows/deploy.yml` reads API and UI image tags from `../../helm/agentfarm-api/Chart.yaml` and `../../helm/agentfarm-ui/Chart.yaml`.
- LiteLLM and PostgreSQL charts run upstream images and have no `appVersion`; bump only chart `version` when their chart templates change.

Documentation-only changes do not change a service image and do not require an `appVersion` bump.

## Operational safety

- Treat signing-key and encryption-key rotation as migrations: existing tokens or encrypted values depend on the current keys.
- Verify migration and secret-hook behavior when changing API chart startup.
- Keep runtime/platform differences explicit when changing Hermes, OpenClaw, Slack, or Teams deployment configuration.
- Use the existing deployment workflow rather than manually publishing mutable production tags.
