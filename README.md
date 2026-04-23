# AAI Labs Starter: Next.js + FastAPI

Monorepo starter with:

- `api/`: FastAPI, SQLModel/SQLAlchemy, Alembic, Injector DI, pytest
- `web/`: Next.js App Router, React, TypeScript, TanStack Query, Playwright

API is served under `/api/v1` and frontend requests to `/api/*` are proxied to backend.

## Project Structure

```text
.
├── api/
├── web/
├── compose.yml
├── Makefile
└── AGENTS.md
```

## Prerequisites

- Python `>=3.14`
- [uv](https://github.com/astral-sh/uv)
- Node.js `>=20`
- [pnpm](https://pnpm.io/)
- Docker (optional, for full local stack)

## Setup

Install dependencies:

```bash
cd api && uv sync
cd ../web && pnpm install
```

Environment:

- API reads env from repo root `.env`
- Optional test env file: `.env.spec`

## Run Locally

From repo root:

- API: `make dev-api`
- Web: `make dev-web`

With Docker (db + api + web):

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
- Web tests: `make test-web`
- Web E2E headed/debug:

```bash
cd web
pnpm test:watch
pnpm test:debug
```

## Lint and Type Checks

- API checks: `make check-api`
- API auto-fix: `make fix-api`
- Web lint: `make lint-web`
- Web typecheck:

```bash
cd web
pnpm -s tsc --noEmit
```

## Development Conventions

See [AGENTS.md](./AGENTS.md) for detailed implementation standards, including:

- how to create new API and Web domains
- architecture boundaries (routes/services/repositories)
- query key and API client patterns
- testing patterns and examples
