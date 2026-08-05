# CommerceOS — Backend

![CI](https://github.com/harshil68190/CommerceOS/actions/workflows/ci.yml/badge.svg)

CommerceOS is a commerce platform backend built with a modular FastAPI
architecture. This repository contains the backend service: FastAPI +
SQLAlchemy 2.x + Alembic + PostgreSQL + Redis, with JWT authentication,
RBAC, products, inventory, and orders modules.

## Stack

Python 3.13 · FastAPI · SQLAlchemy 2.x · Alembic · PostgreSQL · Redis ·
Docker / Docker Compose · Pydantic v2 · uvicorn

## Project layout

```
backend/
├── app/
│   ├── main.py             # app factory, lifespan, middleware wiring
│   ├── api_router.py       # aggregates all /api/v1 routers
│   ├── core/                # config, logging, security, exceptions
│   ├── db/                  # SQLAlchemy engine/session + Redis client
│   ├── middleware/          # request-ID + centralized exception handling
│   ├── models/              # shared ORM models (user, product)
│   ├── modules/             # feature modules: auth, products, inventory, orders
│   ├── schemas/             # auth/product request/response schemas
│   └── workers/             # background task infrastructure
├── alembic/                 # migrations
├── tests/                   # pytest suite (263 tests)
├── scripts/                 # helper scripts (e.g. run_tests.ps1)
├── requirements.txt
├── Dockerfile
├── entrypoint.sh
├── .env.example
├── .env.production.example  # production env template (no secrets)
└── .dockerignore
```

At the repo root: `docker-compose.yml` (base), `docker-compose.dev.yml`
(development overlay), and `render.yaml` (production deployment blueprint
for Render).

## Docker setup

### Prerequisites

- **Docker** with the **Compose v2** plugin (`docker compose`, not
  `docker-compose`). On Windows/macOS install Docker Desktop; on Linux
  install Docker Engine + the compose plugin.
- No local PostgreSQL/Redis needed — the compose stack provides them as
  containers.

### 1. Configure environment variables

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set a real `JWT_SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

> Never commit `.env` (it is git-ignored). Secrets are injected via
> environment variables, never hardcoded.

### 2. Build the images

```bash
docker compose build
```

### 3. Start the stack (one-command startup)

```bash
docker compose up -d
```

This starts `postgres`, `redis`, and `backend`. The backend only starts
once Postgres and Redis report **healthy** (Compose `depends_on:
condition: service_healthy`). The backend's `entrypoint.sh` automatically
runs `alembic upgrade head` **before** uvicorn binds, so migrations are
applied on every startup — no separate step required.

Verify:

```bash
curl http://localhost:8000/api/v1/health
# {"status":"healthy"}

docker compose ps
# should show all three services as "running" / "healthy"
```

### 4. Hot reload (local development)

The base compose file runs uvicorn **without** `--reload` (production
mode). For a fast local dev loop, layer the dev override on top:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

The dev override mounts `backend/app`, `backend/alembic`, and
`backend/scripts` into the container and runs uvicorn with `--reload`, so
host code changes are reflected immediately without rebuilding.

## Docker Compose commands

Useful commands:

```bash
# Build only
docker compose build

# Build + start in foreground (logs follow)
docker compose up --build

# Start in background (detached)
docker compose up -d --build

# Stream logs
docker compose logs -f backend

# Exec into the backend container
docker compose exec backend bash

# Stop the stack (keeps named volumes/data)
docker compose down

# Stop AND delete named volumes (wipe postgres/redis data)
docker compose down -v

# Restart a single service
docker compose restart backend
```

## Running migrations

Migrations run automatically on container startup via `entrypoint.sh`.
You can also run them manually:

```bash
# Apply all pending migrations
docker compose exec backend alembic upgrade head

# Show current revision
docker compose exec backend alembic current

# Generate a new migration from model changes (dev)
docker compose exec backend alembic revision --autogenerate -m "description"
```

## Running tests inside Docker

The full pytest suite (263 tests) needs a **test** database with "test"
in its name and a live Redis — matching `backend/.env.test`. The compose
stack's `postgres`/`redis` services can host the test run:

```bash
# 1. Create the test database in the postgres container
docker compose exec postgres psql -U commerceos -c \
  "CREATE DATABASE commerceos_test;"

# 2. Run the suite inside the backend container
docker compose exec backend \
  env COMMERCEOS_ENV_FILE=.env.test \
  pytest
```

> The test fixtures (see `tests/conftest.py`) require `ENVIRONMENT=test`
> and a database name containing "test". `backend/.env.test` points at
> `postgresql+psycopg://postgres:...@localhost:5432/commerceos_test` for
> **native** runs; for in-container runs override `DATABASE_URL` and
> `REDIS_URL` to the compose service names, e.g.:

```bash
docker compose exec -e COMMERCEOS_ENV_FILE=.env.test \
  -e DATABASE_URL="postgresql+psycopg://commerceos:commerceos@postgres:5432/commerceos_test" \
  -e REDIS_URL="redis://redis:6379/15" \
  backend pytest
```

## Running locally without Docker

Requires a local PostgreSQL and Redis instance (or point `DATABASE_URL` /
`REDIS_URL` at existing ones).

```bash
python3 -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # edit DATABASE_URL / REDIS_URL / JWT_SECRET_KEY

uvicorn app.main:app --reload
```

## Running tests natively

```bash
# Windows PowerShell
.\scripts\run_tests.ps1

# or directly (requires a test DB + live Redis configured in .env.test)
$env:COMMERCEOS_ENV_FILE=".env.test"
pytest
```

## Continuous Integration (GitHub Actions)

The repository ships a production-quality CI pipeline in
`.github/workflows/ci.yml`. It runs automatically on **every push to
`main`** and on **every pull request targeting `main`**.

### How the pipeline works

1. **Checkout** the repository (`actions/checkout@v4`).
2. **Set up Python 3.12** (`actions/setup-python@v5`) with **pip caching**
   keyed on `backend/requirements.txt`, so unchanged dependencies are
   restored from cache instead of reinstalled on every run.
3. **Install dependencies** from `backend/requirements.txt`.
4. **Start PostgreSQL 16 + Redis 7** as GitHub Actions *services*, each
   with a health check, so the job only proceeds once they are ready.
5. **Create a dedicated test database** (`commerceos_test`) — the test
   suite (`tests/conftest.py`) refuses to run against any database whose
   name does not contain "test".
6. **Apply Alembic migrations** (`alembic upgrade head`) against the test
   database.
7. **Run the full pytest suite with coverage**:
   ```
   pytest --cov=app --cov-report=term-missing \
          --cov-report=xml:coverage.xml \
          --cov-report=html:htmlcov \
          --cov-fail-under=80
   ```
   The build **fails** if any test fails **or** if total coverage drops
   below **80%**.
8. **Upload the coverage report** (XML + HTML) as a workflow artifact so
   per-file coverage can be inspected after each run.

### CI badge

The badge at the top of this README reflects the latest run of the
`ci.yml` workflow on the default branch. It only shows a passing status
**after the workflow has actually run on GitHub** — until then it will
render as "no status" / "not found".

### Local verification commands

You can reproduce what CI does locally before pushing. The simplest path
uses the existing Docker Compose stack for Postgres/Redis:

```bash
# 1. Start Postgres & Redis (the backend service is not needed for tests)
docker compose up -d postgres redis

# 2. Create the test database inside the postgres container
docker compose exec postgres psql -U commerceos -c \
  "CREATE DATABASE commerceos_test;"

# 3. Run the suite with the same coverage gates CI enforces
docker compose exec -e COMMERCEOS_ENV_FILE=.env.test \
  -e DATABASE_URL="postgresql+psycopg://commerceos:commerceos@postgres:5432/commerceos_test" \
  -e REDIS_URL="redis://redis:6379/15" \
  backend pytest --cov=app --cov-report=term-missing \
  --cov-report=xml:coverage.xml --cov-report=html:htmlcov \
  --cov-fail-under=80
```

> Ensure `backend/.env.test` exists and is configured (see the
> "Running tests" sections above). The workflow injects the same
> environment variables inline instead of relying on a committed
> `.env.test`.

## Production Deployment

This section documents how to deploy the CommerceOS backend to
**production** using **Render**.

### Platform choice: Render

We chose **Render** because it fits this project's "production-quality
without over-engineering" balance best:

- **Managed PostgreSQL** and **managed Redis** add-ons (TLS, automated
  backups, optional high availability) — no self-hosting of stateful
  services, no manual failover/backup engineering.
- **Blueprint (`render.yaml`) as Infrastructure-as-Code** — the whole
  stack (web service, one-off migration job, Postgres, Redis) is declared
  in one committed file, matching how this repo already treats
  `docker-compose.yml` and the CI workflow as code.
- **Zero-downtime deployments**, **auto-deploy from GitHub** on push to
  `main`, and a **built-in health check** that maps cleanly onto the
  readiness endpoint.
- **Docker-native**: it runs the existing `backend/Dockerfile` directly,
  so no new runtime configuration is needed.

*Alternatives considered:* Railway (similar DX but Render's blueprint +
managed Postgres/Redis is a cleaner IaC fit); Fly.io (more control but
`flyctl` + manual TLS/backups adds ops burden); a VPS with docker-compose
(runs the existing Docker setup but requires manual TLS, backups,
monitoring, and process supervision).

> **Status:** `render.yaml` is a **validated configuration blueprint**.
> It has **NOT** been deployed to a live Render account, so deployment is
> **not yet verified**. Follow "Remaining manual actions" below to perform
> the first real deployment.

### Required environment variables

See `backend/.env.production.example` for a fully documented template.
The variables the app reads are:

| Variable | Required | Notes |
|----------|----------|-------|
| `ENVIRONMENT` | yes | `production` |
| `DATABASE_URL` | yes | Render auto-injects via `fromDatabase`; the app normalizes `postgres://`/`postgresql://` to the psycopg v3 driver |
| `REDIS_URL` | yes | Render auto-injects via `fromRedis`; `rediss://` (TLS) is supported natively by the redis client |
| `JWT_SECRET_KEY` | yes | **Secret** — set manually in the Render dashboard; long random value |
| `CORS_ORIGINS` | yes | Comma-separated browser origins; must be the deployed frontend URL |
| `DEBUG` | no | Must be `false` in production (the app **fails fast** if `DEBUG=true` with `ENVIRONMENT=production`) |
| `LOG_LEVEL` | no | e.g. `INFO`; overrides the DEBUG-derived default |
| `WEB_CONCURRENCY` | no | uvicorn worker count; default `1`, recommended `2`+ |
| `RUN_MIGRATIONS` | no | `false` on the web service (migrations run as a separate job); `true` for local/single-node |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | no | SQLAlchemy pool tuning; keep modest for the managed PG connection limit |

### Migration strategy (safe Alembic runs)

- In **local dev / single-node Compose**, `entrypoint.sh` runs
  `alembic upgrade head` on every container start (idempotent — safe).
- In **production**, migrations run as a **separate one-off job**
  (`commerceos-migrations` in `render.yaml`) that executes
  `alembic upgrade head` and exits. The web service sets
  `RUN_MIGRATIONS=false` so it never races with the migration job when
  multiple web instances start together.
- `alembic upgrade head` is **idempotent**: it only applies pending
  migrations. For added safety against concurrent runs, you can wrap the
  migration in a PostgreSQL **advisory lock** (see below).
- Each migration is a transaction; `alembic downgrade -1` rolls back the
  most recent one if needed.

Optional advisory-lock pattern for the migration job:

```bash
# Run this instead of a bare `alembic upgrade head` to make concurrent
# migration runs safe (one wins, others wait):
psql "$DATABASE_URL" -c "SELECT pg_advisory_lock(724172417);" \
  && alembic upgrade head \
  ; psql "$DATABASE_URL" -c "SELECT pg_advisory_unlock(724172417);"
```

### Deployment steps

1. **Create a Render account** at <https://render.com> and connect your
   GitHub repository.
2. **Import the Blueprint**: In the Render dashboard go to
   **New + → Blueprint**, select the CommerceOS repo, and Render
   provisions `commerceos-db`, `commerceos-redis`,
   `commerceos-migrations`, and `commerceos-api` from `render.yaml`.
3. **Set the secrets** (Render generates placeholder values; replace them):
   - `JWT_SECRET_KEY` on the `commerceos-api` service — generate with
     `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
   - `CORS_ORIGINS` on `commerceos-api` — set to your deployed frontend
     origin (e.g. `https://app.onrender.com` or a custom domain).
4. **Run the migration job** once: trigger `commerceos-migrations`
   manually (or let the first deploy run it) so the schema is created
   before the API serves traffic.
5. **Deploy the API**: Render auto-deploys on push to `main`. The web
   service boots, waits for its health check to pass at
   `/api/v1/health/ready`, and starts serving once Postgres and Redis are
   reachable.
6. **Verify** (see next section).

### Production verification

- **Health/liveness**: `curl https://<api-url>/api/v1/health` →
  `{"status":"healthy"}`.
- **Readiness**: `curl https://<api-url>/api/v1/health/ready` →
  `{"status":"ready"}` (HTTP 200). If Postgres or Redis is unreachable it
  returns HTTP 503 with the failing dependencies.
- **Docs**: `/docs` and `/redoc` are **disabled** in production (return
  404), so the interactive API reference is not exposed.
- **Logs**: Render's log viewer shows the structured JSON logs (one line
  per request with `request_id`).
- **DB**: confirm the Alembic `alembic_version` table exists and lists the
  head revision.

### Rollback considerations

- **Code rollback**: Render keeps the previous deployment. From the
  service's **Deploy** tab, choose the last good deploy and click
  **Deploy** to roll back the API code.
- **Database rollback**: If a migration is bad, run
  `alembic downgrade -1` in the migration job (or a shell against the
  service) to roll back the most recent migration. **Never** roll the app
  code back past a migration that has already been applied to the DB —
  the app code at the old revision expects the old schema.
- **Secrets**: store `JWT_SECRET_KEY` in Render's secret store. Rotate it
  only during a planned maintenance window (rotating invalidates all
  outstanding JWTs).
- **Data**: the managed Postgres has automatic backups (enabled in
  `render.yaml`). Test a backup restore in a staging environment before
  relying on it in an emergency.

### Remaining manual actions (before deployment is verified)

1. Create a Render account and connect the GitHub repo.
2. Import `render.yaml` as a Blueprint.
3. Set the real `JWT_SECRET_KEY` and `CORS_ORIGINS` secrets.
4. Trigger the first deploy and the `commerceos-migrations` job.
5. Verify the public `/api/v1/health` and `/api/v1/health/ready` endpoints
   and that `/docs` is disabled.
6. (Later) Add CI-driven deployment automation once the first manual
   deployment is confirmed working.

## What's intentionally NOT in this milestone

- No task/queue workers (Celery/RQ) — `app/workers/` exists, unused.
- No rate limiting.
- No async SQLAlchemy driver — sync engine in FastAPI's threadpool is
  deliberate (see `app/db/session.py`).

See the CommerceOS architecture document for the full design and the
module roadmap.
