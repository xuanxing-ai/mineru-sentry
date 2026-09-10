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

# Discover image build/pull type (local vs docker)
image_type_from_file=$(grep -E '^[[:space:]]*MINERU_IMAGE_TYPE=' "$env_file" 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')
MINERU_IMAGE_TYPE="${MINERU_IMAGE_TYPE:-${image_type_from_file:-local}}"
export MINERU_IMAGE_TYPE

if [ "$MINERU_IMAGE_TYPE" = "docker" ]; then
	export MINERU_PULL_POLICY="${MINERU_PULL_POLICY:-missing}"
else
	export MINERU_PULL_POLICY="${MINERU_PULL_POLICY:-never}"
fi

prepare_images() {
	if [ "$MINERU_IMAGE_TYPE" = "docker" ]; then
		echo "MINERU_IMAGE_TYPE=docker: 本地构建 sentry，从 Docker 仓库拉取 mineru_worker..."
		docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" build sentry
		echo "从 Docker 仓库拉取 mineru_worker 镜像..."
		docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" pull mineru_worker
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
	echo "==> 2/4 [Download] 下载 MinerU 模型权重..."
	run_download
	echo "==> 3/4 [Create] 创建待机 Worker 容器..."
	docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" create mineru_worker
	echo "==> 4/4 [Up] 后台启动网关服务..."
	exec docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" up -d sentry
fi

if [ "${1:-}" = "build" ] && [ "$MINERU_IMAGE_TYPE" = "docker" ]; then
	shift
	if [ $# -gt 0 ]; then
		for target in "$@"; do
			if [ "$target" = "mineru_worker" ]; then
				echo "MINERU_IMAGE_TYPE=docker: 跳过本地编译，从 Docker 仓库拉取 mineru_worker 镜像..."
				docker compose --env-file "$env_file" -f "$deploy_directory/compose.yaml" pull mineru_worker
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
