#!/bin/sh
set -eu

# Standalone helper script to launch a PostgreSQL container if needed.
# MinerU-Sentry only connects to PostgreSQL; you can run PostgreSQL anywhere.

deploy_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$deploy_directory/.." && pwd)

# Load configuration if available
if [ -r "$project_root/core/config/.env.prod" ]; then
	set -a
	. "$project_root/core/config/.env.prod"
	set +a
fi

CONTAINER_NAME="${POSTGRES_CONTAINER_NAME:-mineru-postgres}"
POSTGRES_USER="${POSTGRES_USERNAME:-mineru_admin}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-mineru_password}"
POSTGRES_DB="${POSTGRES_DATABASE:-mineru_sentry}"
PORT="${POSTGRES_PORT:-5432}"
IMAGE="${POSTGRES_IMAGE:-postgres:16-alpine}"

echo "Starting PostgreSQL container: $CONTAINER_NAME on port $PORT..."
exec docker run -d \
	--name "$CONTAINER_NAME" \
	--restart unless-stopped \
	-e POSTGRES_USER="$POSTGRES_USER" \
	-e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
	-e POSTGRES_DB="$POSTGRES_DB" \
	-p "$PORT":5432 \
	-v mineru_pgdata:/var/lib/postgresql/data \
	"$IMAGE"
