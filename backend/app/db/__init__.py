"""
db/ — everything related to obtaining a database/cache connection.

Per the architecture doc, this is the ONLY package that knows how to
construct a SQLAlchemy engine/session or a Redis client. No other module
(models, services, repositories) should build its own engine or
connection — they all depend on `get_db` / `get_redis` from here.

No ORM models live in this package (see `app/models/` in a future
milestone) — this package is purely about connection/session plumbing.
"""
