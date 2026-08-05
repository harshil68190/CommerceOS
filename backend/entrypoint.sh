#!/usr/bin/env bash
#
# entrypoint.sh
#
# Responsibility: the container's single entrypoint. It guarantees that
# Alembic migrations have been applied to the database BEFORE the API
# server binds, which is what makes "one-command startup" work:
#
#   docker compose up --build
#
# runs migrations automatically, then starts uvicorn. This removes the
# need to remember a separate `alembic upgrade head` step when bringing
# the stack up for the first time (or after pulling new migrations).
#
# Design notes:
#   - `set -euo pipefail` makes the script fail fast: if migrations
#     fail, the server never starts, surfacing the error clearly in
#     `docker logs` instead of a confusing "table does not exist" API
#     error later.
#   - `exec` replaces the shell with uvicorn so signals (SIGTERM/SIGINT)
#     are delivered directly to uvicorn, enabling clean shutdown and
#     correct container lifecycle handling by the orchestrator.
#   - The migration step is idempotent: `alembic upgrade head` only
#     applies migrations that haven't run yet, so every container start
#     is safe.
#   - The actual uvicorn invocation comes from CMD (the image default) or
#     is overridden by docker-compose.dev.yml (which adds --reload via
#     `command:`). We `exec "$@"` so those args are forwarded verbatim —
#     this is what makes hot reload work in dev without baking it into
#     the production image.
#
# NOTE (production): running migrations automatically on every container
# start is the right default for a single-node local/Compose workflow.
# In a scaled production deploy you may instead prefer to run
# `alembic upgrade head` as a separate one-off job to avoid concurrent
# migration races — see the README.

set -euo pipefail

# RUN_MIGRATIONS defaults to "true" (matching the app's default). In
# production (Render), migrations are run as a separate one-off job and
# RUN_MIGRATIONS=false is set on the web service to avoid concurrent
# migration races when multiple web instances start together.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "[entrypoint] Applying Alembic migrations..."
    alembic upgrade head
    echo "[entrypoint] Migrations applied."
fi

echo "[entrypoint] Command: $*"
exec "$@"
