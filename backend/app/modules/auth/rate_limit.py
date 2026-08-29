import hashlib

from fastapi import Request
from redis import Redis

from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededError

settings = get_settings()


def _client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"
    # Proxy header trust belongs at the deployment boundary.  Accepting this
    # header here lets a direct client pick a new IP for every request.
    return request.client.host


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def enforce_rate_limit(
    redis_client: Redis,
    *,
    request: Request,
    scope: str,
    identifier: str | None = None,
    limit: int | None = None,
    window_seconds: int | None = None,
) -> None:
    limit = limit if limit is not None else settings.AUTH_LOGIN_RATE_LIMIT
    window_seconds = window_seconds if window_seconds is not None else settings.AUTH_RATE_LIMIT_WINDOW_SECONDS
    if limit <= 0:
        return

    ip = _client_ip(request)
    # Always enforce a per-IP bucket.  For login/registration, also enforce
    # a per-identity bucket so one IP cannot spray a single account; the IP
    # bucket prevents bypassing either limit with a stream of new emails.
    key_materials = [f"ip:{ip}"]
    if identifier:
        key_materials.append(f"identifier:{identifier.casefold()}")
    counts = []
    for key_material in key_materials:
        key = f"auth:rate_limit:{scope}:{_fingerprint(key_material)}"
        current = redis_client.incr(key)
        if current == 1:
            redis_client.expire(key, window_seconds)
        counts.append(current)

    if any(current > limit for current in counts):
        raise RateLimitExceededError(
            "Too many requests. Please try again later.",
            {"retry_after_seconds": window_seconds, "limit": limit},
        )
