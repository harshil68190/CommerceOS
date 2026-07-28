"""
schemas/ — Pydantic v2 request/response DTOs.

Deliberately separate from `app/models/` (SQLAlchemy ORM classes): a
schema describes what the API sends/receives over the wire, a model
describes what's persisted. Changing an internal column name should
never be forced to also change the public API shape, and vice versa.
"""
