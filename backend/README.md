# CommerceOS — Backend

This is the **backend foundation** milestone of CommerceOS: application
skeleton, database/Redis wiring, middleware, and Docker orchestration.
No business features (auth, catalog, orders, etc.) exist yet — see the
CommerceOS architecture document for the full system design and the
roadmap of upcoming modules.

## Stack

Python 3.13 · FastAPI · SQLAlchemy 2.x · Alembic · PostgreSQL · Redis ·
Docker / Docker Compose · Pydantic v2 · uvicorn

## Project layout

```
backend/
├── app/
│   ├── main.py            # app factory, lifespan, middleware wiring
│   ├── api_router.py       # aggregates all /api/v1 routers (health check today)
│   ├── core/                # config, logging, exception hierarchy, constants
│   ├── db/                  # SQLAlchemy engine/session + Redis client
│   ├── middleware/          # request-ID + centralized exception handling
│   └── workers/             # reserved for future background task processing
├── alembic/                # migrations (no tables yet — no models exist)
├── tests/                   # pytest suite
├── scripts/                 # future one-off/admin scripts
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Running locally with Docker (recommended)

```bash
cp .env.example .env
# edit .env if needed — defaults work for local docker-compose out of the box

docker compose up --build
```

This starts `postgres`, `redis`, and `backend`. The backend only starts
once Postgres and Redis report healthy. Once up:

```bash
curl http://localhost:8000/api/v1/health
# {"status":"healthy"}
```

## Running locally without Docker

Requires a local PostgreSQL and Redis instance (or point `DATABASE_URL`
/ `REDIS_URL` at existing ones).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # edit DATABASE_URL / REDIS_URL to point at localhost

uvicorn app.main:app --reload
```

## Running tests

```bash
pip install -r requirements.txt
pytest
```

The current test suite only exercises the health endpoint — it requires
no live database or Redis connection.

## Migrations

Alembic is initialized and wired to the app's `Settings`/`Base.metadata`,
but there are no models and no migrations yet. Once the first models are
added (`app/models/`, a future milestone):

```bash
alembic revision --autogenerate -m "create initial tables"
alembic upgrade head
```

## What's intentionally NOT in this milestone

- No ORM models, no tables.
- No feature modules (auth, catalog, orders, ...).
- No Celery/RQ task implementations (folder exists, empty).
- No caching logic (Redis connection is wired, unused).
- No rate limiting.

These are all deliberate scope boundaries — see the CommerceOS
architecture document for where each lands in the module roadmap.
