# 从本地 MinerU 源码部署

在 `mineru-sentry` 仓库根目录执行以下命令。MinerU 源码使用 `/home/hsiong/Project/Python/MinerU`；模型、缓存和解析数据统一放在 `/usr/model/MinerU`。

## 1. 确认前置条件

需要 Linux、RTX 5090 驱动、Docker Engine、Compose 2.17+ 和支持命名构建上下文的 BuildKit。

```bash
nvidia-smi
docker compose version
docker buildx version
test -f /home/hsiong/Project/Python/MinerU/pyproject.toml
```

如果 Docker 尚未配置 NVIDIA Container Toolkit，先按 [NVIDIA 安装说明](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)安装，然后执行一次：

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

已有 GPU 容器能正常运行时无需重复配置。重启 Docker 会影响现有容器。Compose 中的 `device_ids` 负责给 MinerU 容器分配指定显卡；默认选择设备 `0`，请用 `nvidia-smi -L` 核对它是 RTX 5090。

## 2. 配置环境（单一配置文件）

所有配置统一合并在单一配置文件中（默认读取 `core/config/.env.dev`，支持通过 `CONFIG_FILE_PATH` 切换）：

```bash
# 复制配置模板
cp core/config/.env.example core/config/.env.dev
$EDITOR core/config/.env.dev
```

- **配置统一**：网关、GPU Worker、Docker Compose 均从同一个 `.env` / `settings.py` 读取，无需分散维护多个 env 文件。
- **自动生成 `mineru.json`**：无需手动维护 `/usr/model/MinerU/mineru.json`，系统会在启动时根据 `settings.py` 自动生成。
- **PostgreSQL 仅负责连接**：本项目只负责连接 PostgreSQL，不强绑数据库运行位置。你可以使用已有独立数据库、宿主机数据库或任何容器。如需快速启动独立 PostgreSQL 容器，可运行：
  ```bash
  ./docs/deploy/postgres.sh
  ```

## 3. 部署与启动 (Deploy & Launch)

### Option A: 首次一键初始化 (One-click Initial Setup, Recommended)
自动按序执行镜像构建、模型下载、待机 Worker 创建及网关启动：
```bash
./docs/deploy/compose.sh init
```

### Option B: 分步执行 (Step-by-Step)
```bash
# 1. 构建镜像
./docs/deploy/compose.sh build sentry mineru_worker

# 2. 下载模型到统一目录（已有完整模型可跳过）
./docs/deploy/compose.sh download

# 3. 创建待机 Worker，启动网关
./docs/deploy/compose.sh create mineru_worker
./docs/deploy/compose.sh up -d sentry
```

日常快速启动：
```bash
./docs/deploy/compose.sh start
```

检查状态与健康检查：
```bash
./docs/deploy/compose.sh --profile worker ps -a
curl --fail-with-body http://localhost:8080/health
```

- Worker 首次应为 `created`，休眠后为 `exited`；未唤醒时 `mineru_api_healthy=false` 属正常现象。
- 仅发布网关的 `8080` 端口；网关与 Worker 通过内部网络或 Docker 通信。

## 6. 调用 API，直接得到结果

完整结果：

```bash
curl --fail-with-body http://localhost:8080/api/v1/parse \
  -F 'file=@document.pdf' \
  -F 'backend=hybrid-engine' \
  -F 'effort=medium'
```

流式返回已完成批次：

```bash
curl -N --fail-with-body http://localhost:8080/api/v1/parse/stream \
  -F 'file=@document.pdf'
```

`backend`、`effort` 在请求中传入，省略时分别为 `hybrid-engine`、`medium`。同名同内容同选项的未完成文件自动续跑，已完成文件直接返回完整 Markdown。首次解析会自动唤醒 Worker；无活动任务且空闲 900 秒后网关停止 Worker 释放 5090 显存。

## 日志与维护

```bash
sudo ./docs/deploy/compose.sh logs -f --tail=100 sentry
curl --fail-with-body http://localhost:8080/api/v1/system/gpu/status
```

修改 MinerU 源码后，在没有活动任务时执行：

```bash
sudo ./docs/deploy/compose.sh build mineru_worker
sudo ./docs/deploy/compose.sh stop mineru_worker
sudo ./docs/deploy/compose.sh create --force-recreate mineru_worker
```
