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

## 3. 从源码构建镜像

```bash
sudo ./docs/deploy/compose.sh config --quiet
sudo ./docs/deploy/compose.sh build sentry mineru_worker
```

- [compose.sh](docs/deploy/compose.sh) 统一读取 `.env.dev` 与 [compose.yaml](docs/deploy/compose.yaml)。
- [mineru-api.Dockerfile](docs/deploy/mineru-api.Dockerfile) 通过构建上下文读取本地 MinerU 源码生成 wheel 并安装，直接以 `mineru-api` 启动，不需要额外的 entrypoint 脚本。
- [sentry.Dockerfile](docs/deploy/sentry.Dockerfile) 为独立网关镜像。

构建完成后，检查 GPU 和已安装的源码包：

```bash
sudo ./docs/deploy/compose.sh run --rm --no-deps mineru_worker python3 -c \
  'import torch, mineru; from importlib.metadata import version; print(mineru.__file__); print(version("mineru")); print(torch.cuda.get_device_name(0)); print(torch.ones(1, device="cuda").item())'
```

## 4. 下载模型到统一目录

首次部署且本地尚未准备完整模型时执行（下载源和模型类型直接读取 `.env` 中的 `MINERU_DOWNLOAD_SOURCE` 和 `MINERU_DOWNLOAD_MODELS`，无需手敲任何参数）：

```bash
sudo ./docs/deploy/compose.sh download
```

模型保存在宿主机挂载目录 `/usr/model/MinerU/cache/` 中，后续容器直接读取，无需重复下载。已有模型可直接跳过。

## 5. 创建待机 Worker，启动网关

```bash
sudo ./docs/deploy/compose.sh create mineru_worker
sudo ./docs/deploy/compose.sh up -d sentry
sudo ./docs/deploy/compose.sh --profile worker ps -a
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
