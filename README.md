# Agent Farm

Monorepo with:

- `api/`: FastAPI, SQLModel/SQLAlchemy, Alembic, Injector DI, pytest
- `ui/`: Next.js App Router, React, TypeScript, TanStack Query, Playwright

API is served under `/api/v1` and frontend requests to `/api/*` are proxied to backend.

## Features Included

Authentication:

- Sign up and login
- Access + refresh token flow (refresh token cookie support)
- Current-user profile read/update (`/auth/me`)
- Change password
- Forgot/reset password endpoints
- Logout

Users:

- Paginated user listing (super admin only)
- User deletion (super admin only)

Organizations:

- Single default organization
- List, get, update, and delete organizations
- Organization filtering support

Authorization and role-aware UX:

- Super-admin-gated pages/components (users and organizations admin screens)
- Different dashboard experience for super admins vs regular users

Frontend foundations:

- App Router auth pages (`/login`, `/signup`)
- Protected dashboard shell with sidebar navigation
- TanStack Query + centralized query-key patterns + Zod schemas

Backend foundations:

- Versioned API routing under `/api/v1`
- Health endpoint (`/api/v1/health`) checks connectivity to db
- Startup bootstrap for default superuser and default organization

## Project Structure

```text
.
├── api/
├── ui/
├── compose.yml
├── Makefile
└── AGENTS.md
```

## Prerequisites

- Python `>=3.14`
- [uv](https://github.com/astral-sh/uv)
- Node.js `>=20`
- [pnpm](https://pnpm.io/)
- Docker (required for Postgres)

## Setup

Install dependencies:

```bash
cd api && uv sync
cd ../ui && pnpm install
```

Environment:

- API reads env from repo root `.env`
- Optional test env file: `.env.spec`

## First-Time Run (Required)

Postgres is run via Docker for this project. Before starting API/UI for the first time:

```bash
make db-up
make migrate
```

Then choose how to run API/UI:

1. Run API + UI directly on host:
   - API: `make dev-api`
   - UI: `make dev-ui`
2. Run full stack in Docker (db + api + ui):
   - `make up`

## Run Locally

From repo root:

- API: `make dev-api`
- UI: `make dev-ui`

With Docker (db + api + ui):

- Start: `make up`
- Stop: `make down`
- DB only: `make db-up`

## Database Migrations (API)

- Apply latest: `make migrate`
- Roll back one: `make rollback`
- Create migration: `make makemigrations`

## Tests

- API tests: `make test-api`
- API coverage: `make coverage`
- UI tests: `make test-ui`
- UI E2E headed/debug:

```bash
cd ui
pnpm test:watch
pnpm test:debug
```

## Lint and Type Checks

- API checks: `make check-api`
- API auto-fix: `make fix-api`
- UI lint: `make lint-ui`
- UI typecheck:

```bash
cd ui
pnpm -s tsc --noEmit
```

## Development Conventions

See [AGENTS.md](./AGENTS.md) for detailed implementation standards, including:

- how to create new API and UI domains
- architecture boundaries (routes/services/repositories)
- query key and API client patterns
- testing patterns and examples
