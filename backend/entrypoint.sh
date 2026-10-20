#!/usr/bin/env bash
# Local Docker Compose defaults to applying pending migrations at startup.
# In production, set RUN_MIGRATIONS=false and let Render's preDeployCommand
# run `alembic upgrade head` once before the new web service starts.

set -euo pipefail

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "[entrypoint] Applying Alembic migrations..."
    alembic upgrade head
    echo "[entrypoint] Migrations applied."
fi

echo "[entrypoint] Command: $*"
exec "$@"
