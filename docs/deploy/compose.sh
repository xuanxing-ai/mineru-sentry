#!/bin/sh
set -eu

deploy_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$deploy_directory/../.." && pwd)

printf "请输入环境配置文件名称 [直接回车默认: .env.prod]: "
read -r env_name || env_name=""
env_name="${env_name:-.env.prod}"
env_file="$project_root/core/config/$env_name"

if [ ! -r "$env_file" ]; then
	echo "错误: 环境配置文件不存在或不可读: $env_file" >&2
	exit 1
fi
export CONFIG_FILE_PATH="$env_name"

# Discover image build/pull type (local vs docker)
image_type_from_file=$(grep -E '^[[:space:]]*MINERU_IMAGE_TYPE=' "$env_file" 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')
MINERU_IMAGE_TYPE="${MINERU_IMAGE_TYPE:-${image_type_from_file:-local}}"
export MINERU_IMAGE_TYPE

image_local_from_file=$(grep -E '^[[:space:]]*MINERU_IMAGE_LOCAL=' "$env_file" 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')
image_docker_from_file=$(grep -E '^[[:space:]]*MINERU_IMAGE_DOCKER=' "$env_file" 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')

if [ "$MINERU_IMAGE_TYPE" = "docker" ]; then
	export MINERU_IMAGE="${MINERU_IMAGE:-${image_docker_from_file:-alexsuntop/mineru:3.4.2}}"
	export MINERU_PULL_POLICY="${MINERU_PULL_POLICY:-missing}"
else
	export MINERU_IMAGE="${MINERU_IMAGE:-${image_local_from_file:-mineru-api:5090-source}}"
	export MINERU_PULL_POLICY="${MINERU_PULL_POLICY:-never}"
	export MINERU_CONFIG_FILE="${MINERU_CONFIG_FILE:-/usr/model/MinerU/mineru.json}"
	export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-/usr/model/MinerU/cache/modelscope}"
	export HF_HOME="${HF_HOME:-/usr/model/MinerU/cache/huggingface}"
	export TORCH_HOME="${TORCH_HOME:-/usr/model/MinerU/cache/torch}"
	export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/usr/model/MinerU/cache}"
fi

shm_size_from_file=$(grep -E '^[[:space:]]*MINERU_SHM_SIZE=' "$env_file" 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')
MINERU_SHM_SIZE="${MINERU_SHM_SIZE:-${shm_size_from_file:-16gb}}"
export MINERU_SHM_SIZE

gpu_mem_size_from_file=$(grep -E '^[[:space:]]*GPU_MEMORY_UTILIZATION_SIZE=' "$env_file" 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')
GPU_MEMORY_UTILIZATION_SIZE="${GPU_MEMORY_UTILIZATION_SIZE:-${gpu_mem_size_from_file:-}}"
export GPU_MEMORY_UTILIZATION_SIZE

prepare_images() {
	if [ "$MINERU_IMAGE_TYPE" = "docker" ]; then
		if [ -z "${MINERU_IMAGE:-}" ]; then
			echo "错误: MINERU_IMAGE_TYPE=docker 时必须在配置文件中指定有效的 MINERU_IMAGE_DOCKER。" >&2
			echo "提示: MinerU 官方未在 Docker Hub 发布预构建镜像。若需本地源码编译，请设置 MINERU_IMAGE_TYPE=local。" >&2
			exit 1
		fi
		echo "MINERU_IMAGE_TYPE=docker: 本地构建 sentry，从仓库拉取 mineru_worker ($MINERU_IMAGE)..."
		docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" build sentry
		echo "从仓库拉取 mineru_worker 镜像..."
		if ! docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" pull mineru_worker; then
			echo "错误: 拉取 mineru_worker 镜像失败 ($MINERU_IMAGE)。" >&2
			echo "提示: MinerU 官方未在公共 Docker Hub 发布预构建镜像。若需本地源码编译，请设置 MINERU_IMAGE_TYPE=local。" >&2
			exit 1
		fi
	else
		echo "MINERU_IMAGE_TYPE=local: 本地源码编译构建服务镜像 (sentry, mineru_worker)..."
		docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" build sentry mineru_worker
	fi
}

run_download() {
	# Extract download options from the environment file if not set in process environment
	download_source=$(grep -E '^[[:space:]]*MINERU_DOWNLOAD_SOURCE=' "$env_file" 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')
	download_models=$(grep -E '^[[:space:]]*MINERU_DOWNLOAD_MODELS=' "$env_file" 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')
	source_flag="${MINERU_DOWNLOAD_SOURCE:-${download_source:-modelscope}}"
	models_flag="${MINERU_DOWNLOAD_MODELS:-${download_models:-all}}"

	echo "Using configuration from: $env_file"
	echo "Downloading MinerU models (source: $source_flag, models: $models_flag)..."
	docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" \
		run --rm --no-deps mineru_worker mineru-models-download -s "$source_flag" -m "$models_flag" "$@"

	base_model_dir="${MINERU_CONFIG_FILE%/*}"
	base_model_dir="${base_model_dir:-/usr/model/MinerU}"
	if [ -d "$base_model_dir" ]; then
		if [ ! -e "$base_model_dir/pipeline" ]; then
			for p in "$base_model_dir/cache/modelscope/models/OpenDataLab/PDF-Extract-Kit-1.0" "$base_model_dir/cache/modelscope/models/OpenDataLab/PDF-Extract-Kit-1___0"; do
				if [ -d "$p" ]; then
					ln -sfn "$p" "$base_model_dir/pipeline" 2>/dev/null || true
					break
				fi
			done
		fi
		if [ ! -e "$base_model_dir/vlm" ]; then
			for p in "$base_model_dir/cache/modelscope/models/OpenDataLab/MinerU2.5-Pro-2605-1.2B" "$base_model_dir/cache/modelscope/models/OpenDataLab/MinerU2___5-Pro-2605-1___2B"; do
				if [ -d "$p" ]; then
					ln -sfn "$p" "$base_model_dir/vlm" 2>/dev/null || true
					break
				fi
			done
		fi
	fi
}

if [ "${1:-}" = "download" ]; then
	shift
	run_download "$@"
	exit 0
fi

if [ "${1:-}" = "init" ]; then
	shift
	echo "==> 1/4 [Images] 准备镜像 (模式: $MINERU_IMAGE_TYPE)..."
	prepare_images
	if [ "$MINERU_IMAGE_TYPE" = "local" ]; then
		echo "==> 2/4 [Download] 下载 MinerU 模型权重至宿主机..."
		run_download
	else
		echo "==> 2/4 [Download] MINERU_IMAGE_TYPE=docker (默认使用镜像内置模型)，跳过模型下载步骤..."
	fi
	echo "==> 3/4 [Create] 创建待机 Worker 容器..."
	docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" create mineru_worker
	echo "==> 4/4 [Up] 后台启动网关服务..."
	docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" up -d sentry
	sleep 2
	container_name=$(docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" ps -a --format '{{.Name}}' sentry)
	echo "==> 网关启动日志 (docker logs ${container_name:-mineru-sentry}):"
	docker logs "${container_name:-mineru-sentry}"
	exit 0
fi

if [ "${1:-}" = "build" ] && [ "$MINERU_IMAGE_TYPE" = "docker" ]; then
	shift
	if [ $# -gt 0 ]; then
		for target in "$@"; do
			if [ "$target" = "mineru_worker" ]; then
				if [ -z "${MINERU_IMAGE:-}" ]; then
					echo "错误: MINERU_IMAGE_TYPE=docker 时必须在配置文件中指定有效的 MINERU_IMAGE_DOCKER。" >&2
					echo "提示: MinerU 官方未在 Docker Hub 发布预构建镜像。若需本地源码编译，请设置 MINERU_IMAGE_TYPE=local。" >&2
					exit 1
				fi
				echo "MINERU_IMAGE_TYPE=docker: 跳过本地编译，从仓库拉取 mineru_worker 镜像 ($MINERU_IMAGE)..."
				if ! docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" pull mineru_worker; then
					echo "错误: 拉取 mineru_worker 镜像失败 ($MINERU_IMAGE)。" >&2
					echo "提示: MinerU 官方未在公共 Docker Hub 发布预构建镜像。若需本地源码编译，请设置 MINERU_IMAGE_TYPE=local。" >&2
					exit 1
				fi
			else
				docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" build "$target"
			fi
		done
		exit 0
	else
		prepare_images
		exit 0
	fi
fi

if [ "${1:-}" = "start" ]; then
	shift
	echo "==> 确保待机 Worker 容器存在..."
	docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" create mineru_worker
	echo "==> 后台启动网关服务..."
	exec docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" up -d sentry "$@"
fi

if [ $# -eq 0 ]; then
	echo "MinerU-Sentry Compose 管理脚本"
	echo "配置文件: $env_file"
	echo "镜像模式 (MINERU_IMAGE_TYPE): $MINERU_IMAGE_TYPE (docker: 远端拉取, local: 本地源码编译)"
	echo ""
	echo "常用快捷命令:"
	echo "  $0 init        # 【首次一键部署】准备镜像 ($MINERU_IMAGE_TYPE) -> 下载模型 -> 创建待机 Worker -> 启动网关"
	echo "  $0 start       # 【日常一键启动】确保创建待机 Worker -> 启动网关"
	echo "  $0 download    # 单独下载/更新 MinerU 模型"
	echo "  $0 logs sentry # 查看网关运行日志"
	echo "  $0 down        # 停止并移除容器"
	echo ""
	echo "高级用法: $0 [docker-compose 原生子命令，如 ps / stop / run 等]"
	exit 0
fi

echo "Using configuration: $env_file"
exec docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" "$@"

