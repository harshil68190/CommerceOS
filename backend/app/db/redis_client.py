"""
db/redis_client.py

Responsibility
--------------
Creates a single Redis connection pool for the application process and
exposes `get_redis`, the FastAPI dependency future modules will use to
reach Redis.

This milestone wires the connection only — per the architecture doc,
Redis's three roles (session/refresh-token store, rate-limit counters,
cache-aside for hot catalog data) are implemented by the modules that
need them, not here. This file has exactly one job: "give me a working
Redis client," nothing more.

A connection pool (not a single connection) is used so concurrent
requests can each borrow a connection without blocking on one another,
mirroring how the SQLAlchemy engine pool works in `db/session.py`.
"""

from collections.abc import Generator

import redis

from app.core.config import get_settings

settings = get_settings()

# `redis.ConnectionPool` is process-wide and thread-safe; created once at
# import time, just like the SQLAlchemy engine.
redis_pool = redis.ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,  # return str instead of bytes — simplest default
    # for this stage; a future module can override per-call if it ever
    # needs to store binary data.
)


def get_redis() -> Generator[redis.Redis, None, None]:
    """
    FastAPI dependency that yields a Redis client borrowed from the shared
    pool.

    Usage (in a future module):
        def endpoint(cache: redis.Redis = Depends(get_redis)): ...

    Unlike a SQLAlchemy Session, a `redis.Redis` client is a thin wrapper
    around the pool and doesn't need an explicit transaction/close per
    request, but we still yield it via a generator dependency for
    consistency with `get_db` and to keep a single obvious pattern for
    all "give me a connection" dependencies in the app.
    """
    client = redis.Redis(connection_pool=redis_pool)
    try:
        yield client
    finally:
        client.close()
