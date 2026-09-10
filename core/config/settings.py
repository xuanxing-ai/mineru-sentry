"""Shared configuration loaded from a selected file and process environment."""
import json
import os
from pathlib import Path
from typing import Optional

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
DEFAULT_MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS = (
	env.get("DEFAULT_MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS")
	or env.get("MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS")
	or env.get("WORKER_STARTUP_TIMEOUT_SECONDS")
)
WORKER_STARTUP_TIMEOUT_SECONDS = DEFAULT_MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS

# Shared storage paths used by the gateway and worker.
SHARED_DATA_DIR = env.get("SHARED_DATA_DIR")
MINERU_CONFIG_FILE = env.get("MINERU_CONFIG_FILE")

# MinerU Model paths and sources.
MINERU_PIPELINE_MODEL_DIR = env.get("MINERU_PIPELINE_MODEL_DIR")
MINERU_VLM_MODEL_DIR = env.get("MINERU_VLM_MODEL_DIR")
MINERU_MODEL_SOURCE = env.get("MINERU_MODEL_SOURCE")
MINERU_DEVICE_MODE = env.get("MINERU_DEVICE_MODE")

# MinerU Worker API configuration.
MINERU_API_HOST = env.get("MINERU_API_HOST")
MINERU_API_PORT = env.get("MINERU_API_PORT")
MINERU_API_ENABLE_VLM_PRELOAD = env.get("MINERU_API_ENABLE_VLM_PRELOAD")
MINERU_API_OUTPUT_ROOT = env.get("MINERU_API_OUTPUT_ROOT")
MINERU_PROCESSING_WINDOW_SIZE = env.get("MINERU_PROCESSING_WINDOW_SIZE")
MINERU_API_MAX_CONCURRENT_REQUESTS = env.get("MINERU_API_MAX_CONCURRENT_REQUESTS")
MINERU_API_ENABLE_FASTAPI_DOCS = env.get("MINERU_API_ENABLE_FASTAPI_DOCS")
MINERU_API_TASK_RETENTION_SECONDS = env.get("MINERU_API_TASK_RETENTION_SECONDS")
MINERU_API_TASK_CLEANUP_INTERVAL_SECONDS = env.get("MINERU_API_TASK_CLEANUP_INTERVAL_SECONDS")

# Table, formula, and OCR recognition settings.
MINERU_FORMULA_ENABLE = env.get("MINERU_FORMULA_ENABLE")
MINERU_FORMULA_CH_SUPPORT = env.get("MINERU_FORMULA_CH_SUPPORT")
MINERU_TABLE_ENABLE = env.get("MINERU_TABLE_ENABLE")
MINERU_TABLE_MERGE_ENABLE = env.get("MINERU_TABLE_MERGE_ENABLE")
MINERU_OCR_DET_MASK_INLINE_FORMULA_ENABLE = env.get("MINERU_OCR_DET_MASK_INLINE_FORMULA_ENABLE")

# MinerU Model download and cache configuration.
MINERU_DOWNLOAD_SOURCE = env.get("MINERU_DOWNLOAD_SOURCE")
MINERU_DOWNLOAD_MODELS = env.get("MINERU_DOWNLOAD_MODELS")
MODELSCOPE_CACHE = env.get("MODELSCOPE_CACHE")
HF_HOME = env.get("HF_HOME")
TORCH_HOME = env.get("TORCH_HOME")
XDG_CACHE_HOME = env.get("XDG_CACHE_HOME")

# Container image build and deploy configuration.
MINERU_IMAGE_TYPE = env.get("MINERU_IMAGE_TYPE")
MINERU_SOURCE_DIR = env.get("MINERU_SOURCE_DIR")
MINERU_BASE_IMAGE = env.get("MINERU_BASE_IMAGE")
MINERU_IMAGE = env.get("MINERU_IMAGE")
SENTRY_IMAGE = env.get("SENTRY_IMAGE")
MINERU_GPU_DEVICE_ID = env.get("MINERU_GPU_DEVICE_ID")
MINERU_SHM_SIZE = env.get("MINERU_SHM_SIZE")
SENTRY_BIND_ADDRESS = env.get("SENTRY_BIND_ADDRESS")
SENTRY_PUBLISHED_PORT = env.get("SENTRY_PUBLISHED_PORT")

# Durable PDF checkpoint size and per-batch worker polling deadline.
PARSE_BATCH_PAGES = env.get("PARSE_BATCH_PAGES")
DEFAULT_MINERU_TASK_RESULT_TIMEOUT_SECONDS = (
	env.get("DEFAULT_MINERU_TASK_RESULT_TIMEOUT_SECONDS")
	or env.get("MINERU_TASK_RESULT_TIMEOUT_SECONDS")
	or env.get("WORKER_TASK_TIMEOUT_SECONDS")
)
WORKER_TASK_TIMEOUT_SECONDS = DEFAULT_MINERU_TASK_RESULT_TIMEOUT_SECONDS

# Default document parsing options.
DEFAULT_BACKEND = env.get("DEFAULT_BACKEND")
DEFAULT_EFFORT = env.get("DEFAULT_EFFORT")
DEFAULT_PARSE_METHOD = env.get("DEFAULT_PARSE_METHOD")
DEFAULT_FORMULA_ENABLE = env.get("DEFAULT_FORMULA_ENABLE")
DEFAULT_TABLE_ENABLE = env.get("DEFAULT_TABLE_ENABLE")
DEFAULT_IMAGE_ANALYSIS = env.get("DEFAULT_IMAGE_ANALYSIS")


def generate_mineru_config(target_path: Optional[str] = None) -> Optional[str]:
	"""Generate mineru.json dynamically from settings without manual user intervention."""
	config_path_str = target_path or MINERU_CONFIG_FILE or "/usr/model/MinerU/mineru.json"
	config_file = Path(config_path_str)
	pipeline_dir = MINERU_PIPELINE_MODEL_DIR or str(config_file.parent / "pipeline")
	vlm_dir = MINERU_VLM_MODEL_DIR or str(config_file.parent / "vlm")
	model_source = MINERU_MODEL_SOURCE or "modelscope"

	content = {
		"models-dir": {
			"pipeline": pipeline_dir,
			"vlm": vlm_dir,
		},
		"model-source": model_source,
		"latex-delimiter-config": {
			"display": {"left": "$$", "right": "$$"},
			"inline": {"left": "$", "right": "$"},
		},
		"config_version": "1.3.2",
	}

	try:
		config_file.parent.mkdir(parents=True, exist_ok=True)
		with open(config_file, "w", encoding="utf-8") as f:
			json.dump(content, f, indent=4, ensure_ascii=False)
		print(f"Generated MinerU configuration at: {config_file}")
		return str(config_file)
	except (OSError, PermissionError) as exc:
		print(f"Notice: skipped writing {config_file}: {exc}")
		return None


# Automatically ensure mineru.json is generated upon settings initialization
generate_mineru_config()

if __name__ == "__main__":
	generate_mineru_config()
