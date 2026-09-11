"""Shared configuration loaded from a selected file and process environment."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path when invoked directly as a script
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
	sys.path.insert(0, _project_root)

from core.util.env_util import load_env

CONFIG_FILE_PATH = os.getenv("CONFIG_FILE_PATH", ".env.prod")
print(f"ENV_PATH: {CONFIG_FILE_PATH}")
env = load_env(CONFIG_FILE_PATH)

# Server and logging configuration.
SERVICE_PORT = env.get("SERVICE_PORT")
SENTRY_HOST = env.get("SENTRY_HOST")
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
MINERU_IMAGE_TYPE = env.get("MINERU_IMAGE_TYPE") or "local"
MINERU_IMAGE_LOCAL = env.get("MINERU_IMAGE_LOCAL") or "mineru-api:5090-source"
MINERU_IMAGE_DOCKER = env.get("MINERU_IMAGE_DOCKER") or "alexsuntop/mineru:3.4.2"
MINERU_IMAGE = (
	MINERU_IMAGE_DOCKER
	if MINERU_IMAGE_TYPE == "docker" and MINERU_IMAGE_DOCKER
	else (env.get("MINERU_IMAGE") or MINERU_IMAGE_LOCAL)
)
MINERU_SOURCE_DIR = env.get("MINERU_SOURCE_DIR")
MINERU_BASE_IMAGE = env.get("MINERU_BASE_IMAGE")
SENTRY_IMAGE = env.get("SENTRY_IMAGE")
MINERU_GPU_DEVICE_ID = env.get("MINERU_GPU_DEVICE_ID")
MINERU_SHM_SIZE = env.get("MINERU_SHM_SIZE")
GPU_MEMORY_UTILIZATION_SIZE = env.get("GPU_MEMORY_UTILIZATION_SIZE")
GPU_MEMORY_UTILIZATION = env.get("GPU_MEMORY_UTILIZATION")
SENTRY_BIND_ADDRESS = env.get("SENTRY_BIND_ADDRESS")

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


def _resolve_or_link_model_dir(
	base_dir: Path,
	configured_dir_str: Optional[str],
	repo_mode: str,
	candidate_rel_paths: list[str],
) -> str:
	"""
	Resolve model directory and link cache models to default paths if not present.
	:param base_dir: Base model storage root directory.
	:param configured_dir_str: Explicit directory path from settings or None.
	:param repo_mode: Mode name, either 'pipeline' or 'vlm'.
	:param candidate_rel_paths: List of relative paths under base_dir to search for cached models.
	:return: Resolved directory path string.
	"""
	target_path = Path(configured_dir_str) if configured_dir_str else (base_dir / repo_mode)
	if target_path.exists():
		return str(target_path)

	for candidate_rel in candidate_rel_paths:
		candidate_path = base_dir / candidate_rel
		if candidate_path.exists():
			try:
				target_path.symlink_to(candidate_path)
				print(f"Created symlink for {repo_mode}: {target_path} -> {candidate_path}")
				return str(target_path)
			except (OSError, PermissionError):
				return str(candidate_path)

	return str(target_path)


def generate_mineru_config(target_path: Optional[str] = None) -> Optional[str]:
	"""Generate mineru.json dynamically from settings without manual user intervention."""
	config_path_str = target_path or MINERU_CONFIG_FILE or "/usr/model/MinerU/mineru.json"
	config_file = Path(config_path_str)
	base_dir = config_file.parent

	pipeline_candidates = [
		"cache/modelscope/models/OpenDataLab/PDF-Extract-Kit-1.0",
		"cache/modelscope/models/OpenDataLab/PDF-Extract-Kit-1___0",
		"cache/huggingface/models/opendatalab/PDF-Extract-Kit-1.0",
	]
	pipeline_dir = _resolve_or_link_model_dir(
		base_dir=base_dir,
		configured_dir_str=MINERU_PIPELINE_MODEL_DIR,
		repo_mode="pipeline",
		candidate_rel_paths=pipeline_candidates,
	)

	vlm_candidates = [
		"cache/modelscope/models/OpenDataLab/MinerU2.5-Pro-2605-1.2B",
		"cache/modelscope/models/OpenDataLab/MinerU2___5-Pro-2605-1___2B",
		"cache/huggingface/models/opendatalab/MinerU2.5-Pro-2605-1.2B",
	]
	vlm_dir = _resolve_or_link_model_dir(
		base_dir=base_dir,
		configured_dir_str=MINERU_VLM_MODEL_DIR,
		repo_mode="vlm",
		candidate_rel_paths=vlm_candidates,
	)

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




def compute_gpu_memory_utilization(
	target_size_str: Optional[str] = None,
	total_vram_gb: Optional[float] = None,
) -> Optional[float]:
	"""
	Calculate the vLLM gpu_memory_utilization ratio based on the target memory size string.
	:param target_size_str: Target memory string like '16gb', '8gb', '12g', or '8192mb'.
	:param total_vram_gb: Optional total GPU VRAM in GB. If omitted, attempts to auto-detect.
	:return: Calculated float ratio (e.g. 0.5025) clamped between 0.05 and 0.95, or None.
	"""
	raw_target = target_size_str or GPU_MEMORY_UTILIZATION_SIZE
	if not raw_target:
		return None
	
	cleaned_target = raw_target.strip().lower()
	regex_pattern = r"^([0-9.]+)\s*(gb|g|mb|m)?$"
	matched_result = re.match(regex_pattern, cleaned_target)
	if not matched_result:
		return None
	
	size_str = matched_result.group(1)
	unit_str = matched_result.group(2) or "gb"
	parsed_value = float(size_str)
	is_gb = unit_str in ("gb", "g")
	requested_gb = parsed_value if is_gb else (parsed_value / 1024.0)
	
	detected_vram_gb = total_vram_gb
	if detected_vram_gb is None:
		try:
			query_args = ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]
			command_output = subprocess.check_output(query_args, text=True, stderr=subprocess.DEVNULL)
			output_line = command_output.strip().split("\n")[0].strip()
			if output_line:
				detected_vram_gb = float(output_line) / 1024.0
		except Exception:
			pass
	
	if detected_vram_gb and detected_vram_gb > 0:
		computed_ratio = requested_gb / detected_vram_gb
		bounded_ratio = min(max(computed_ratio, 0.05), 0.95)
		rounded_ratio = round(bounded_ratio, 4)
		return rounded_ratio
	
	return None


if not GPU_MEMORY_UTILIZATION and GPU_MEMORY_UTILIZATION_SIZE:
	calculated_ratio = compute_gpu_memory_utilization(target_size_str=GPU_MEMORY_UTILIZATION_SIZE)
	if calculated_ratio is not None:
		GPU_MEMORY_UTILIZATION = str(calculated_ratio)


# Automatically ensure mineru.json is generated upon settings initialization
generate_mineru_config()

if __name__ == "__main__":
	generate_mineru_config()

