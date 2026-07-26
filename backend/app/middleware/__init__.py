"""
middleware/ — request-scoped, cross-cutting behavior applied uniformly to
every incoming request regardless of which router/module handles it.

This milestone includes request-ID propagation and centralized exception
handling. Rate limiting (Redis-backed, per the architecture doc) is added
in a later milestone once there are authenticated endpoints worth
protecting.
"""
