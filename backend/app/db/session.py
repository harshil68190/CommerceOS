"""
db/session.py

Responsibility
--------------
Creates the single SQLAlchemy `Engine` and `sessionmaker` for the whole
application, and exposes `get_db`, the FastAPI dependency every future
router/service will use to obtain a request-scoped `Session`.

Design notes
------------
- We use SQLAlchemy 2.x's synchronous engine (via the `psycopg` v3
  driver) rather than the async engine. For a FastAPI app, sync
  SQLAlchemy running in FastAPI's threadpool is simpler to operate,
  easier to debug, and perfectly capable of the throughput this project
  needs at the "100 -> 100,000 users" scale path described in the
  architecture doc (read replicas / pooling solve scale first, not async
  drivers). This keeps Alembic simple too, since Alembic's tooling is
  built around sync engines.
- The engine is created once at import time (module-level singleton) and
  reused for the lifetime of the process — creating a new engine per
  request would exhaust connections.
- `get_db` yields exactly one `Session` per request and guarantees it is
  closed afterwards, including when an exception propagates.
- Connection pool settings are pulled from `Settings` so pool sizing can
  be tuned per environment without touching code.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# The single Engine instance for the application process. SQLAlchemy
# engines are thread-safe and manage their own connection pool internally
# — this must NOT be recreated per request.
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
    pool_pre_ping=True,  # verifies a connection is alive before using it,
    # protecting against stale connections after e.g. a DB restart or a
    # cloud load balancer silently dropping idle connections.
    echo=settings.DB_ECHO,
    future=True,
)

# Session factory bound to the engine above. `expire_on_commit=False`
# means objects remain usable (e.g. for serialization into a response)
# after a commit, without triggering a fresh DB round-trip to refresh
# attributes — the standard choice for a request/response web app.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a request-scoped SQLAlchemy `Session`.

    Usage (in a future module's router):
        def endpoint(db: Session = Depends(get_db)): ...

    The session is always closed after the request finishes, whether it
    succeeded or raised — this prevents connection leaks under load.
    Rollback-on-error is deliberately NOT automatic here: that decision
    belongs to the service layer, which knows the correct transaction
    boundaries for a given business operation (see the architecture
    doc's "Request Lifecycle" section on checkout for why this matters).
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
