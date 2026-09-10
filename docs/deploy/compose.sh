#!/bin/sh
set -eu

deploy_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$deploy_directory/../.." && pwd)

# Discover unified environment configuration
if [ -n "${ENV_FILE:-}" ] && [ -r "$ENV_FILE" ]; then
	env_file="$ENV_FILE"
elif [ -r "$project_root/core/config/.env.dev" ]; then
	env_file="$project_root/core/config/.env.dev"
elif [ -r "$project_root/core/config/.env" ]; then
	env_file="$project_root/core/config/.env"
elif [ -r "$project_root/.env" ]; then
	env_file="$project_root/.env"
elif [ -r "/usr/model/MinerU/.env" ]; then
	env_file="/usr/model/MinerU/.env"
elif [ -r "$project_root/core/config/.env.example" ]; then
	env_file="$project_root/core/config/.env.example"
else
	echo "No environment file found. Please create core/config/.env.dev" >&2
	exit 1
fi

if [ "${1:-}" = "download" ]; then
	shift
	# Extract download options from the environment file if not set in process environment
	download_source=$(grep -E '^[[:space:]]*MINERU_DOWNLOAD_SOURCE=' "$env_file" 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')
	download_models=$(grep -E '^[[:space:]]*MINERU_DOWNLOAD_MODELS=' "$env_file" 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')
	source_flag="${MINERU_DOWNLOAD_SOURCE:-${download_source:-modelscope}}"
	models_flag="${MINERU_DOWNLOAD_MODELS:-${download_models:-all}}"

	echo "Using configuration from: $env_file"
	echo "Downloading MinerU models (source: $source_flag, models: $models_flag)..."
	exec docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" \
		run --rm --no-deps mineru_worker mineru-models-download -s "$source_flag" -m "$models_flag" "$@"
fi

echo "Using configuration: $env_file"
exec docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" "$@"
