# CommerceOS

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)](https://redis.io/)

**A production-oriented, modular-monolith commerce platform** — a full-stack
application with a **FastAPI + SQLAlchemy** backend and a **React + TypeScript**
frontend. CommerceOS is built around real-world e-commerce domains (auth,
catalog, multi-warehouse inventory, and order lifecycle management) with
strict layering, an immutable inventory audit ledger, explicit order state
machines, and a deployment-ready Docker/Render setup.

> **Status:** Feature complete. This is a portfolio showcase project engineered
> to production quality: typed, tested (200+ tests, 80%+ coverage gate),
> containerized, IaC-deployed, and documented end-to-end.

---

## Table of Contents

- [Key Features](#key-features)
- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Screenshots](#screenshots)
- [Project Structure](#project-structure)
- [Local Setup](#local-setup)
- [Docker Setup](#docker-setup)
- [Running Tests](#running-tests)
- [CI/CD](#cicd)
- [Deployment](#deployment)
- [API Documentation](#api-documentation)
- [Future Improvements / Roadmap](#future-improvements--roadmap)
- [License](#license)

---

## Key Features

### Authentication & Authorization
- **JWT access tokens** (short-lived, stateless) + **rotating refresh tokens**
  tracked in Redis for single-use rotation and instant revocation.
- **Role-based access control (RBAC)** across `admin`, `seller`,
  `inventory_manager`, and `customer` roles, enforced via FastAPI dependencies.
- Constant-time login (dummy-hash timing parity) to prevent account
  enumeration.
- Centralized dependency injection for auth via `Depends()`.

### Product Catalog
- Full CRUD with **draft / active / archived / out_of_stock** lifecycle.
- Customer-facing listing strictly limited to `active` products.
- Free-text **search** (name / SKU / description) plus filter (category, brand,
  price range) and sort (price, name, newest).
- Separate admin endpoint exposing all statuses for back-office management.

### Multi-Warehouse Inventory
- **Warehouse CRUD** with soft-delete (reactivation supported).
- A **single source of truth** for stock (`Inventory`), with `product-warehouse`
  uniqueness.
- **Immutable inventory transaction ledger** — *every* stock change writes an
  audit record (add, remove, adjust, reserve, release, confirm, transfer).
- **Stock reservations** for pending orders and **confirmation-on-payment**
  that converts a reservation into a sale.
- **Warehouse-to-warehouse transfers** as atomic paired transactions with a
  shared correlation ID.
- **Low-stock / out-of-stock reports** and an **optimistic concurrency**
  (`version`) + `SELECT ... FOR UPDATE` safety net against overselling.
- **Bulk import** (up to 500 items, atomic).

### Order Lifecycle
- Full **state machine**: `pending → confirmed → shipped → delivered →
  returned → refunded` (cancelled is terminal).
- **Atomic order creation** that snapshots product name/SKU/price and reserves
  inventory in the same transaction.
- **Optimistic concurrency** (`version`) on orders.
- **Inventory integration** throughout: reserve on create, confirm on payment,
  release on cancel/delete, adjust on item quantity changes.
- Per-role permissions (admin / seller / customer ownership).

### Frontend
- **React + TypeScript + Vite** SPA with **TanStack Query** for server state.
- **shadcn/ui + Tailwind CSS** component library, responsive layout.
- **Axios client** with a single-flight **refresh-once** interceptor and a
  normalized error envelope.
- Dedicated pages: Dashboard (KPI + charts), Products, Warehouses, Inventory,
  Orders, Order Detail, and Profile.
- Protected routes + role-gated UI.

### Operational Readiness
- **Liveness** (`/health`) and **readiness** (`/health/ready`) probes that
  verify Postgres + Redis connectivity.
- **Request-ID middleware** and a **centralized structured error envelope**
  (`error_code`, `message`, `details`, `request_id`).
- **Alembic** migrations applied automatically on container startup.
- **Docker Compose** (base + dev overlay) and a **Render Blueprint** for
  IaC-based production deployment.

---

## Architecture Overview

CommerceOS is a **modular monolith**: microservice-shaped module boundaries
(clear ownership, no cross-module DB access, service-layer isolation) without
the operational tax of distributed systems. This is the right call for a
small team and decomposes naturally into microservices later.

```
Client (React + TS SPA)
      │  HTTPS / REST (JSON)  /api/v1/*
      ▼
FastAPI Application (modular monolith)
      ├─ Middleware (CORS, Request-ID, centralized error handler)
      ├─ Routers (auth, products, inventory, orders, health)
      ├─ Services (business logic, cross-module orchestration)
      ├─ Repositories (persistence, SQLAlchemy)
      └─ Models / Schemas (ORM ↔ Pydantic DTOs)
              │                        │
              ▼                        ▼
        PostgreSQL                Redis
        (primary DB)        (refresh tokens / cache-ready)
```

**Layering rule** (enforced by convention): `Router → Service → Repository →
DB`. Routers know nothing about SQLAlchemy; services know nothing about HTTP;
repositories know no business rules. Cross-module calls go through service
interfaces (e.g., `OrderService` calls `StockMovementService`), which is the
seam that enables future microservice extraction.

See **[docs/DIAGRAMS.md](docs/DIAGRAMS.md)** for Mermaid diagrams of the
high-level architecture, backend request flow, database ER model, order
lifecycle, and inventory lifecycle.

---

## Tech Stack

### Backend
| Layer | Technology |
|-------|-----------|
| Language | Python 3.13 |
| Web framework | FastAPI (Uvicorn) |
| ORM / Migrations | SQLAlchemy 2.x (typed, `Mapped[]`) + Alembic |
| Database | PostgreSQL 16 |
| Cache / token store | Redis 7 |
| Validation | Pydantic v2 + pydantic-settings |
| Auth | PyJWT + pwdlib (bcrypt) |
| Testing | pytest + httpx + pytest-cov |

### Frontend
| Layer | Technology |
|-------|-----------|
| Language | TypeScript 5.6 |
| Framework | React 18 + Vite 5 |
| Server state | TanStack Query 5 |
| HTTP | Axios (refresh-once interceptor) |
| Styling | Tailwind CSS 3 + shadcn/ui (Radix) |
| Forms / Validation | React Hook Form + Zod |
| Charts | Recharts |
| State (client) | Zustand (theme / toast) |
| Routing | React Router 6 |

### DevOps
- Docker / Docker Compose (base + dev overlay)
- GitHub Actions CI (referenced; see [CI/CD](#cicd))
- Render Blueprint (`render.yaml`) for production IaC

---

## Screenshots

> Placeholders — add real images here as they are captured. See
> [docs/GITHUB_READINESS.md](docs/GITHUB_READINESS.md) for a full screenshot
> checklist.

| | |
|---|---|
| **Login** | ![Login](docs/screenshots/login.png "Login") |
| **Dashboard** | ![Dashboard](docs/screenshots/dashboard.png "Dashboard") |
| **Products** | ![Products](docs/screenshots/products.png "Products") |
| **Inventory** | ![Inventory](docs/screenshots/inventory.png "Inventory") |
| **Orders** | ![Orders](docs/screenshots/orders.png "Orders") |
| **Order Detail** | ![Order Detail](docs/screenshots/order-detail.png "Order Detail") |

*(Create a `docs/screenshots/` folder and drop in PNGs named as above.)*

---

## Project Structure

```
CommerceOS/
├── README.md                     # This file (top-level overview)
├── docs/                         # Architecture diagrams + readiness docs
│   ├── DIAGRAMS.md
│   ├── RESUME_READINESS.md
│   ├── GITHUB_READINESS.md
│   └── PORTFOLIO_READINESS.md
├── backend/                      # FastAPI modular-monolith service
│   ├── app/
│   │   ├── main.py               # App factory, lifespan, middleware wiring
│   │   ├── api_router.py         # Aggregates all /api/v1 routers + health
│   │   ├── core/                 # config, logging, security, exceptions
│   │   ├── db/                   # SQLAlchemy engine/session + Redis client
│   │   ├── middleware/           # request-ID + centralized error handling
│   │   ├── models/               # shared ORM models (user, product)
│   │   ├── modules/              # feature modules: auth, products, inventory, orders
│   │   ├── schemas/              # auth/product request/response schemas
│   │   └── workers/              # Redis pool used by health/ops
│   ├── alembic/                  # migrations
│   ├── tests/                    # pytest integration suite
│   ├── scripts/                  # helper scripts (run_tests.ps1)
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── README.md                 # Backend-specific docs (setup, tests, deploy)
├── frontend/                     # React + TypeScript SPA
│   ├── src/
│   │   ├── components/           # shadcn/ui + shared/widget components
│   │   ├── features/             # feature-sliced pages (auth, dashboard, products, ...)
│   │   ├── lib/                  # api client, query, auth, validators
│   │   ├── stores/               # zustand stores (theme, toast)
│   │   └── types/                # shared TS types
│   ├── package.json
│   ├── vite.config.ts
│   └── README.md                 # Frontend-specific docs
├── docker-compose.yml            # base compose (backend, postgres, redis)
├── docker-compose.dev.yml        # dev overlay (hot reload)
└── render.yaml                   # Render Blueprint (production IaC)
```

---

## Local Setup

> The **fastest path** is Docker (below). For a native dev loop, follow these
> steps. Both require a PostgreSQL 16 and Redis 7 instance reachable via
> `DATABASE_URL` / `REDIS_URL`.

### Prerequisites
- Python 3.13+
- Node.js 20+ / npm
- PostgreSQL 16 and Redis 7 (local or reachable over the network)

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # edit DATABASE_URL / REDIS_URL / JWT_SECRET_KEY
alembic upgrade head        # apply schema migrations
uvicorn app.main:app --reload
```

Backend is now at `http://localhost:8000` (docs at `/docs`).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend dev server is at `http://localhost:5173` and proxies `/api` to the
backend (see `vite.config.ts`).

### Local admin bootstrap

Public registration always creates a `customer` account. To create a local admin
account for development, run the controlled bootstrap script from the backend
folder:

```bash
cd backend
python scripts/create_admin.py --email admin@commerceos.local --password 'ChangeMe!123' --first-name Admin --last-name User
```

The script updates an existing user to `ADMIN` if the email already exists, and
never exposes an admin role selector on the public registration page.

---

## Docker Setup

### Prerequisites
- Docker with Compose v2 (`docker compose`). No local Postgres/Redis needed —
  the stack provides them.

### 1. Configure environment

```bash
cp backend/.env.example backend/.env
# set a real JWT_SECRET_KEY:
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### 2. Build & start

```bash
docker compose build
docker compose up -d
```

The backend only starts once Postgres and Redis report **healthy**, and
`entrypoint.sh` runs `alembic upgrade head` automatically before uvicorn binds.

Verify:

```bash
curl http://localhost:8000/api/v1/health
# {"status":"healthy"}
docker compose ps
```

### 3. Hot reload (development)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

The dev overlay mounts `backend/app`, `backend/alembic`, and `backend/scripts`
and runs uvicorn with `--reload`.

### Useful compose commands

```bash
docker compose logs -f backend      # stream logs
docker compose exec backend bash    # shell into backend
docker compose down                 # stop (keeps volumes)
docker compose down -v              # stop + wipe volumes
docker compose exec postgres psql -U commerceos -c "CREATE DATABASE commerceos_test;"
```

---

## Running Tests

Full details in **[backend/README.md](backend/README.md)**. The suite is
**200+ integration tests** requiring a test database (name contains `test`) and
a live Redis.

### Inside Docker (recommended)

```bash
docker compose up -d postgres redis
docker compose exec postgres psql -U commerceos -c "CREATE DATABASE commerceos_test;"
docker compose exec -e COMMERCEOS_ENV_FILE=.env.test \
  -e DATABASE_URL="postgresql+psycopg://commerceos:commerceos@postgres:5432/commerceos_test" \
  -e REDIS_URL="redis://redis:6379/15" \
  backend pytest
```

### Native (Windows PowerShell)

```powershell
cd backend
.\scripts\run_tests.ps1
```

### With coverage gate (matches CI)

```bash
pytest --cov=app --cov-report=term-missing --cov-report=xml:coverage.xml \
       --cov-fail-under=80
```

---

## CI/CD

The backend ships a **GitHub Actions** pipeline that runs on every push/PR to
`main`:

1. Checkout + set up **Python 3.12** with pip caching.
2. Install dependencies from `backend/requirements.txt`.
3. Start **PostgreSQL 16 + Redis 7** as service containers.
4. Create the `commerceos_test` database (the test harness refuses to run on a
   non-`test` DB).
5. Apply Alembic migrations.
6. Run pytest with `--cov-fail-under=80` (build fails below 80% coverage).
7. Upload coverage reports as artifacts.

> **Note:** The workflow file (`.github/workflows/ci.yml`) is referenced and
> documented but is **not currently committed** to the repository. It is a
> remaining improvement to add it (see [Future Improvements](#future-improvements--roadmap)).

Production deployment is automated via the **Render Blueprint** (`render.yaml`)
with auto-deploy on push to `main` (see below).

---

## Deployment

CommerceOS deploys to **production** using **Render** via the committed
`render.yaml` Blueprint (Infrastructure-as-Code). It provisions:

- **Managed PostgreSQL** (`commerceos-db`) with automated backups.
- **Managed Redis** (`commerceos-redis`) with TLS.
- **One-off migration job** (`commerceos-migrations`) that runs
  `alembic upgrade head` before the web service boots.
- **FastAPI web service** (`commerceos-api`) that runs migrations as a separate
  job (`RUN_MIGRATIONS=false`) and exposes `/api/v1/health/ready` + a health
  check.

### Deploy steps

1. Create a Render account and connect the GitHub repo.
2. Import `render.yaml` as a **Blueprint**.
3. Set secrets: `JWT_SECRET_KEY` and `CORS_ORIGINS` (the deployed frontend URL).
4. Trigger the first deploy + the migration job.
5. Verify `/api/v1/health` and `/api/v1/health/ready`; `/docs` is disabled in
   production.

> **Status:** `render.yaml` is a validated configuration blueprint, but has
> **not** been deployed to a live Render account yet. Follow the "Remaining
> manual actions" in **[backend/README.md](backend/README.md)** for the first
> deployment.

---

## API Documentation

Interactive API docs are auto-generated by FastAPI:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/api/v1/openapi.json`

> In production (`ENVIRONMENT=production`), `/docs` and `/redoc` are disabled.

### Endpoint map (all under `/api/v1`)

| Module | Methods & Paths |
|--------|-----------------|
| **Auth** | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` |
| **Products** | `GET /products` (customer), `GET /products/search`, `GET /products/{slug}`, `GET /products/admin`, `POST /products`, `PUT /products/{id}`, `DELETE /products/{id}`, `PATCH /products/{id}/archive` |
| **Inventory** | `GET/POST /inventory/warehouses`, `GET/PUT/DELETE /inventory/warehouses/{id}`, `PATCH /inventory/warehouses/{id}/reactivate`, `GET /inventory`, `GET /inventory/products/{id}`, `POST /inventory/stock/{add,remove,adjust}`, `POST /inventory/{reserve,release,confirm-reservation}`, `POST /inventory/transfers`, `GET /inventory/transactions`, `GET /inventory/reports/low-stock`, `POST /inventory/bulk` |
| **Orders** | `POST /orders`, `GET /orders`, `GET /orders/my`, `GET /orders/{id}`, `PATCH /orders/{id}`, `DELETE /orders/{id}`, `PATCH /orders/{id}/{cancel,confirm-payment,ship,deliver,return,refund}`, plus `/orders/{id}/items` CRUD |
| **Health** | `GET /health` (liveness), `GET /health/ready` (readiness) |

### Error format

All errors use a consistent envelope:

```json
{
  "error_code": "NOT_FOUND",
  "message": "No order found with id '...'.",
  "details": {},
  "request_id": "..."
}
```

---

## Future Improvements / Roadmap

CommerceOS is feature complete for its current scope. The following items are
**planned / future work** (not yet implemented) — see the implemented-vs-planned
split in **[CommerceOS_Architecture.md](CommerceOS_Architecture.md)**:

### Near-term (engineering completeness)
- **Commit the GitHub Actions CI workflow** (`.github/workflows/ci.yml`) — the
  pipeline is fully documented and reproducible locally but the file is not yet
  in the repo.
- **Frontend production build + Dockerfile** for the SPA (currently the frontend
  runs via `npm run dev`; a static build and container are not yet wired into
  the deployment stack).
- **Payment gateway integration** (Stripe/Razorpay) with webhook handling.
- **Background workers** (Celery/RQ) for email, invoice generation, and
  low-stock alerts — `app/workers/` exists but is unused.
- **Rate limiting** (Redis-backed) on auth and public endpoints.

### Product roadmap (from the architecture reference)
- **Cart & Checkout** flow, **coupons**, and **reviews** (verified-purchase).
- **Analytics** dashboards (sales, top products, inventory turnover).
- **Notification service** (email/SMS/push) with per-user preferences.
- **Advanced search** (faceted, typo-tolerance) via a dedicated engine.
- **Return/Refund (RMA)** workflow as a first-class module.
- **Multi-vendor marketplace** enhancements (seller payouts, commissions).
- **Internationalization** (multi-language, multi-currency, regional tax).
- **Fraud detection** on checkout.
- **Event sourcing** for orders if audit/replay requirements grow.

---

## License

This project is provided for **portfolio and demonstration purposes**. No
license is currently applied — all rights reserved by the author. If you intend
to use or distribute it, please contact the author to agree on licensing terms.

---

For detailed backend documentation (env vars, migrations, tests, Render
deployment), see **[backend/README.md](backend/README.md)**.
For frontend documentation, see **[frontend/README.md](frontend/README.md)**.
