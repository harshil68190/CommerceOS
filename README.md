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
- [CommerceOS Intelligence](#commerceos-intelligence)
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

## CommerceOS Intelligence

CommerceOS Intelligence is an admin-only **inventory decision engine** built on
the orders and inventory data CommerceOS already stores. It answers three
questions for every product × warehouse position: *how much will we sell, when
do we run out, and how much should we order?* No new tables and no seeded or
mock data: every number is derived from live `orders`, `order_items`,
`inventory`, `products`, and `warehouses` rows.

### Why it differentiates CommerceOS

Most order-management projects stop at CRUD and a "low stock" flag, which only
reacts after stock is already thin. Intelligence is **forward-looking and
explainable**: it converts demand history into a stockout date, a risk level,
and a purchase quantity, and shows the arithmetic behind each. Every formula is
a transparent baseline (moving averages, a lead-time risk rule, a classic
safety-stock reorder point), so each result can be reproduced by hand and
defended, with no black-box model.

### Architecture

A separate module following the existing Router → Service → Repository layering
(`backend/app/modules/intelligence/`):

| File | Responsibility |
|------|----------------|
| `router.py` | HTTP layer, admin-only dependency, query validation |
| `service.py` | Orchestration: loads data, runs the engine per position, aggregates KPIs and simulations |
| `repository.py` | Two read-only SQL queries (stock positions, daily demand); returns plain dataclasses |
| `engine.py` | Composes forecast → projection → risk → reorder for one position (no I/O) |
| `forecasting.py` | Daily series, moving averages, σ, confidence, rolling backtest, WAPE (pure) |
| `projection.py` | Days of cover, stockout day/date, projected inventory (pure) |
| `risk.py` | Risk classification with human-readable reasons (pure) |
| `reorder.py` | Safety stock, reorder point, order-up-to, quantity (pure) |
| `constants.py` | Every tunable number and enum in one place |

Business logic lives in pure functions with no database, clock, or randomness,
so outputs are deterministic and unit-testable. The clock is injected
(`get_today` dependency) so API tests pin the date.

Frontend: `frontend/src/features/intelligence/` (dashboard, product detail,
what-if page), admin-only via `RequireRole`, with sidebar and Dashboard entry
points.

### Formulas and logic

**Demand.** Units on `CONFIRMED`, `SHIPPED`, and `DELIVERED` orders, summed per
product × warehouse × calendar day (by `orders.created_at`, UTC), over the last
60 *completed* days (today is excluded because it is incomplete). `PENDING`
(unpaid; already visible as reserved stock), `CANCELLED`, `RETURNED`, and
`REFUNDED` orders are not demand. Days with no sales are zeros. Days before a
position existed are *not* counted as zero-demand days (history starts at the
inventory row's creation or first sale), so new products are not under-forecast.

**Forecast.** With `MA_w` = mean of the last `w` days (or all days if fewer):

```
daily_rate = 0.5 × MA7 + 0.3 × MA14 + 0.2 × MA30
forecast_demand(H) = daily_rate × H            H ∈ {7, 14, 30}
σ = sample standard deviation of the last 30 days
```

Confidence: `none` (no sales), `low` (<14 days of history), `medium` (<30),
`high` (≥30). Forecast error is measured with a one-step-ahead rolling backtest
over the last 14 days (each day forecast using only earlier days) and reported
as WAPE `= Σ|actual − forecast| / Σactual`. The dashboard shows it as a
percentage ("Forecast error (WAPE)"); lower is better, and it is blank when
nothing sold in the window.

**Projection and stockout.** `available = quantity − reserved_quantity`.

```
days_of_cover = available / daily_rate
stockout day d* = ceil(available / daily_rate)      stockout_date = today + (d* − 1)
projected_stock(d) = max(0, available − daily_rate × d)
```

No demand means no stockout date. Zero stock with demand means out today.

**Risk** (`L` = lead time, default 7 days). Boundaries are inclusive on the
riskier side:

| Days of cover | Risk |
|---------------|------|
| ≤ 1 × L (or already out) | High |
| ≤ 2 × L | Medium |
| ≤ 4 × L | Low |
| > 4 × L, or no forecast demand | Healthy |

Floor: if `available ≤ reorder_level` and demand is expected, risk is at least
Medium. Each result carries plain-English reasons.

**Reorder.**

```
lead_time_demand = rate × L
safety_stock     = 1.65 × σ × √L                       (~95% service level)
reorder_point    = max(ceil(lead_time_demand + safety_stock), reorder_level)
target_stock     = max(ceil(rate × (L + H) + safety_stock), reorder_level)
                   capped at max_stock when max_stock > 0
order_quantity   = ceil(target_stock − available)  if available ≤ reorder_point, else 0
```

**What-if.** Demand (rate and σ) is scaled by `1 + percent/100`, the whole
pipeline is re-run, and baseline vs scenario are compared: changed risk
levels, new projected stockouts, and additional reorder units. Nothing is
written to the database.

### Endpoints (admin only, under `/api/v1`)

| Method & path | Purpose |
|---------------|---------|
| `GET /intelligence/dashboard?horizon_days=7\|14\|30&lead_time_days=7&limit=20` | Risk KPIs, high-risk and reorder lists, forecast-vs-actual trend |
| `GET /intelligence/products/{product_id}` | Per-warehouse forecast, projection, stockout date, risk reasoning, itemised reorder maths |
| `POST /intelligence/simulate` | Body: `demand_change_percent` (−100…1000), optional `horizon_days`, `lead_time_days`, `product_id`, `warehouse_id` |

Non-admin roles receive `403`; unauthenticated callers `401`.

### Assumptions and limits

- The schema stores no supplier lead times, so lead time is an explicit
  assumption (default 7 days, overridable per request) and is echoed in every
  response.
- There are no purchase orders, so stock already on order is not netted off
  recommendations.
- Demand during past stockouts is under-observed, so forecasts can run low for
  chronically out-of-stock items.
- A flat daily rate does not model weekday or seasonal patterns; that is a
  natural extension, deliberately left out to stay explainable.

### Tests

`tests/test_intelligence_engine.py` (pure forecasting, stockout, risk
boundaries, reorder maths) and `tests/test_intelligence_api.py` (RBAC,
empty/no-history, demand definition, per-warehouse separation, dashboard,
product detail, simulation) run against the real test database. The module is
at ~99% coverage.

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
| **Intelligence** (admin) | `GET /intelligence/dashboard`, `GET /intelligence/products/{id}`, `POST /intelligence/simulate` |
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
