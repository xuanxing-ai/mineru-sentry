"""Shared configuration loaded from a selected file and process environment."""
import os

from core.util.env_util import load_env

CONFIG_FILE_PATH = os.getenv("CONFIG_FILE_PATH", ".env.dev")
print(f"ENV_PATH: {CONFIG_FILE_PATH}")
env = load_env(CONFIG_FILE_PATH)

# Server and logging configuration; legacy port variables remain supported.
SERVICE_PORT = env.get("SERVICE_PORT")
SENTRY_HOST = env.get("SENTRY_HOST")
SENTRY_PORT = env.get("SENTRY_PORT")
LOG_PATH = env.get("LOG_PATH")
LOG_NAME = env.get("LOG_NAME")
LOG_LEVEL = env.get("LOG_LEVEL")

# POSTGRES_URL accepts a hostname or an existing full SQLAlchemy connection URL.
POSTGRES_URL = env.get("POSTGRES_URL")
POSTGRES_PORT = env.get("POSTGRES_PORT")
POSTGRES_DATABASE = env.get("POSTGRES_DATABASE")
POSTGRES_USERNAME = env.get("POSTGRES_USERNAME")
POSTGRES_PASSWORD = env.get("POSTGRES_PASSWORD")

# Docker and GPU worker lifecycle configuration.
DOCKER_HOST = env.get("DOCKER_HOST")
MINERU_WORKER_CONTAINER_NAME = env.get("MINERU_WORKER_CONTAINER_NAME")
MINERU_API_URL = env.get("MINERU_API_URL")
IDLE_TIMEOUT_SECONDS = env.get("IDLE_TIMEOUT_SECONDS")
WORKER_STARTUP_TIMEOUT_SECONDS = env.get("WORKER_STARTUP_TIMEOUT_SECONDS")

# Shared storage paths used by the gateway and worker.
SHARED_DATA_DIR = env.get("SHARED_DATA_DIR")
MINERU_CONFIG_FILE = env.get("MINERU_CONFIG_FILE")

# Durable PDF checkpoint size and per-batch worker polling deadline.
PARSE_BATCH_PAGES = env.get("PARSE_BATCH_PAGES")
WORKER_TASK_TIMEOUT_SECONDS = env.get("WORKER_TASK_TIMEOUT_SECONDS")
