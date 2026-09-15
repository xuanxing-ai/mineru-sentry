# MinerU-Sentry

[English](../../README.md) | 简体中文

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](../../LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker Compose](https://img.shields.io/badge/Docker_Compose-2.17+-2496ED.svg?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![MinerU Upstream](https://img.shields.io/badge/MinerU-Upstream-orange.svg)](https://github.com/opendatalab/MinerU)

**面向自托管 MinerU 的按需 GPU 网关：通过 HTTP 接收文档解析请求，在 PostgreSQL 中持久化按页断点记录，直接流式返回原始 Markdown 文本，并在空闲时自动停止 Worker 容器以释放 RTX 5090 / 4090 显存。**

[快速开始](#快速开始) · [核心特性](#为什么使用-mineru-sentry) · [解析与流式断点](#解析文档与断点重连) · [架构与生命周期](#架构与-gpu-生命周期) · [运维与接口参考](#运维与-api-参考) · [配置说明](#配置说明)

---

### 终端运行实证

#### 1. 待机零显存占用验证 (0 MB VRAM)
无解析任务运行时，GPU Worker 容器保持为 `created` 或 `exited` 待机状态，**不占用宿主机 GPU 显存**：

```bash
$ curl -s http://localhost:8080/api/v1/system/gpu/status
{
  "container_name": "mineru_gpu_worker",
  "container_status": "created",
  "is_gpu_active": false,
  "idle_countdown_seconds": null,
  "active_tasks_count": 0,
  "mineru_api_healthy": false
}
```

#### 2. HTTP 响应直接返回 Markdown 文本
提交解析任务时系统自动唤醒 Worker 容器，逐页持久化落盘，并在响应体中直接返回拼接好的纯 Markdown 文本，无需解压 ZIP 包：

```bash
$ curl -s --fail-with-body http://localhost:8080/api/v1/parse \
    -F 'file=@attention_paper.pdf' \
    -F 'backend=hybrid-engine' \
    -F 'effort=medium'
# Attention Is All You Need

## Abstract
The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...
```

---

## 为什么使用 MinerU-Sentry

- **待机零显存占用与按需生命周期**：网关与 PostgreSQL 常驻运行，内存开销极低（约 50 MB RAM）。收到解析请求时，网关动态拉起预建好的 GPU Worker 容器；当所有任务完成且空闲超过 15 分钟（可由 `IDLE_TIMEOUT_SECONDS` 配置）后，自动停止 Worker 容器，将 RTX 5090 / 4090 显存彻底交还给本地 LLM 推理或微调任务。
- **直接返回 Markdown 与断点流式输出**：普通解析接口直接在 HTTP 响应体中返回解析完成的纯 Markdown 文本；流式接口（`POST /api/v1/parse/stream`）在连接建立后首先回放已落盘的前缀内容，并实时推送新批次 Markdown。不向调用方返回 ZIP 归档、下载附件或服务器内部磁盘路径。
- **逐页持久化检查点与断点续跑**：PDF 文档默认每页作为一个解析批次（`PARSE_BATCH_PAGES=1`）。每批次结果原子写入磁盘后立即提交数据库检查点。如遇网络中断、超时或服务重启，重新上传即可从最后断点自动继续，无需重新跑已经完成的页面。
- **同名文件去重与任务复用**：上传文件名与 SHA-256 哈希相同的文件时自动复用已有记录：已完成的任务瞬间返回缓存文本；正在运行的任务自动挂载执行流；中断任务自动沿用已有检查点继续解析。
- **单一配置文件极简运维**：网关、Worker 与 Docker Compose 统一从单个环境配置文件读取（默认 `core/config/.env.prod`，可通过 `CONFIG_FILE_PATH` 自定义）。系统启动或唤醒 Worker 时，会自动根据配置生成 `/usr/model/MinerU/mineru.json`，无需手动编写。

> [!NOTE]
> **适用范围与边界：** 单个网关进程管理宿主机上的一个独立 GPU Worker 容器。PDF 文档支持精细的逐页检查点断点恢复；其他格式文档（如 DOCX、PPT）按整份文档粒度执行。

---

## 架构与 GPU 生命周期

### 系统数据流

```mermaid
flowchart LR
    Client[客户端 HTTP 请求] --> Sentry[Sentry HTTP 网关]
    Sentry --> DB[(PostgreSQL 任务与断点记录)]
    Sentry -->|按需启动| Worker[MinerU GPU Worker 容器]
    Worker -->|批次 Markdown 结果| Sentry
    Sentry --> Files[流式落盘 Checkpoint 与拼接结果]
    Sentry -->|直接返回 Markdown / 流式写出| Client
    Sentry -.->|空闲 15 分钟后自动停止| Worker
```

### Worker 容器生命周期状态机

```mermaid
stateDiagram-v2
    [*] --> Standby: compose.sh init / create (0 MB 显存)
    Standby --> Waking: 收到解析请求 (POST /api/v1/parse)
    Standby --> Waking: 手动唤醒 (POST /api/v1/system/gpu/wake)
    Waking --> Active: Worker 健康检查通过 (/health 200 OK)
    Active --> Active: 处理文档批次并落盘 Checkpoint
    Active --> IdleCountdown: 全部活动任务已完成
    IdleCountdown --> Active: 收到新解析任务 (重置倒计时)
    IdleCountdown --> Standby: 空闲超时 (默认 900 秒) -> docker stop (0 MB 显存)
    Active --> Standby: 手动停止 (POST /api/v1/system/gpu/sleep)
```

Compose 未给网关分配 GPU，所有神经网络推理与 OCR 均严格隔离在 GPU Worker 容器中运行。

---

## 快速开始

以下命令在 RTX 5090 / 4090 Linux 主机的仓库根目录执行。需要兼容的 NVIDIA 驱动 (550+)、Docker Engine 24+、NVIDIA Container Toolkit、Compose 2.17+ 和 BuildKit。MinerU 可从 `${MINERU_SOURCE_DIR}` 的本地源码构建；模型、缓存和解析数据统一存放在 `/usr/model/MinerU`。

### 1. 配置环境（单一配置文件）

配置已完全合并在单个环境文件中（默认使用 `core/config/.env.prod`，支持通过 `CONFIG_FILE_PATH` 自定义）：

```bash
# 复制并编辑配置
cp core/config/.env.example core/config/.env.prod
$EDITOR core/config/.env.prod
```

- **配置极简统一**：网关、Worker、Docker Compose 均从同一份 `.env` 文件与 `settings.py` 读取。
- **自动生成 `mineru.json`**：系统启动或唤醒 Worker 时，会自动根据 `settings.py` 生成 `/usr/model/MinerU/mineru.json`，无需用户手工编写和维护。
- **PostgreSQL 仅负责连接**：本项目只连接 PostgreSQL 存储任务状态，无论 PostgreSQL 运行在独立机器、宿主机还是容器均可。如需在本地通过 Docker 快速启动一个独立 PostgreSQL，可执行：
  ```bash
  ./deploy/postgres.sh
  ```

### 2. 部署与启动

#### 首次一键初始化
自动按序完成停止清理旧容器、镜像构建、模型权重下载（至 `/usr/model/MinerU`）、待机 Worker 容器创建以及网关启动：

```bash
./deploy/compose.sh init
```

#### 日常运维操作

```bash
# 启动网关并确保待机 Worker 容器存在
./deploy/compose.sh start

# 停止网关及相关服务
./deploy/compose.sh down

# 查看网关实时日志
./deploy/compose.sh logs -f sentry
```

#### 验证服务状态

```bash
# 网关健康检查
curl --fail-with-body http://localhost:8080/health

# 查看 Worker 容器状态与显存释放倒计时
curl --fail-with-body http://localhost:8080/api/v1/system/gpu/status
```

- **待机机制说明**：Sentry 会在收到解析请求时按需启动待机 Worker 容器；Worker 属于 `worker` profile，空闲 15 分钟（可配置）后自动停止进入 `exited` 状态，彻底释放 5090 显存。
- 宿主机仅发布网关的 `8080` 端口；网关与 Worker 通过内部 Docker 网络通信。

## 解析文档与断点重连

上传同名、同内容且解析选项一致的文件，即可获取或继续同一个任务。同名但内容、解析选项或结束页不同会返回 HTTP 409，避免混用旧结果；请为不同文档或解析版本使用不同文件名。

### 1. 返回完整结果

```bash
curl --fail-with-body http://localhost:8080/api/v1/parse \
  -F 'file=@document.pdf' \
  -F 'backend=hybrid-engine' \
  -F 'effort=medium'
```

已完成的任务直接返回完整 Markdown 文本；未完成的任务继续执行，完成后再返回。调用方不需要下载文件或自行拼接。任务 ID 仅放在 `X-Sentry-Task-ID` 响应头，供诊断使用。

### 2. 按批次流式返回

```bash
curl -N --fail-with-body http://localhost:8080/api/v1/parse/stream \
  -F 'file=@document.pdf'
```

先返回已有的完整前缀，再随新批次完成返回新增文本。每次重连都从文档开头返回，因此新响应应替换上一次部分结果，不能再次追加到旧响应。普通接口和流式接口都会保存检查点。

断开客户端连接不会主动取消后台任务。Worker 批次失败会有限重试；持续失败时普通接口返回 HTTP 502，已经开始的文本流会异常中止。重新上传同名文件即可重试，已完成批次保留。流式输出是批次粒度，不是逐 token 输出。

### 3. 显式指定断点

如果索引 `0`～`208` 的结果已完整保存，第 210 页对应的续跑索引为 `209`：

```bash
curl --fail-with-body http://localhost:8080/api/v1/parse \
  -F 'file=@document.pdf' \
  -F 's=209'
```

也支持表单 `start_page_id=209` 或查询参数 `?s=209`。通常直接重新上传、不传 `s` 即可自动恢复。显式页码不能跳过尚未保存的页面，否则返回 HTTP 409；若检查点已经超过该页，则从实际检查点继续，不重复拼接。

默认检查点文件为 `0_0.md`、`1_1.md` 等，服务端按顺序合并，输出完整文本。提高 `PARSE_BATCH_PAGES` 可减少 Worker 请求数，但未完成批次需整体重跑，跨批次结构也可能受影响。内部落盘位于 `/usr/model/MinerU/data/tasks/<task_id>/`，客户端无需操作这些文件。

已上传过的文件也可仅凭文件名继续或读取最终结果：

```bash
curl --fail-with-body -X POST http://localhost:8080/api/v1/parse/by-filename/document.pdf
```

## 配置说明

所有环境变量与服务配置统一位于单一配置文件中（默认为 `core/config/.env.prod`，支持 `CONFIG_FILE_PATH` 覆盖）。模板位于 [core/config/.env.example](../../core/config/.env.example)。网关在启动时读取该文件；启动或唤醒 Worker 时，会自动根据配置生成 `mineru.json`，无需手动编写。

| 配置项 | 默认值或行为 |
| --- | --- |
| `SERVICE_PORT`、`SENTRY_HOST` | `8080`、`0.0.0.0` |
| `POSTGRES_URL` | 数据库主机名或完整 SQLAlchemy URL；未设置时禁用解析接口 |
| `POSTGRES_PORT` | `5432`；使用主机名时还需设置 `POSTGRES_DATABASE`、`POSTGRES_USERNAME` 和 `POSTGRES_PASSWORD` |
| `MINERU_IMAGE_TYPE` | `local`（本地源码编译，推荐）或 `docker`（从自建/私有 Docker 仓库拉取） |
| `MINERU_IMAGE_LOCAL` | `mineru-api:5090-source`；本地源码编译模式生成的镜像名与标签 |
| `MINERU_IMAGE_DOCKER` | `alexsuntop/mineru:3.4.2`；`docker` 模式下预构建镜像或私有仓库镜像地址 |
| `MINERU_WORKER_CONTAINER_NAME` | `mineru_gpu_worker` |
| `MINERU_SHM_SIZE` | `16gb`；分配给 Worker 容器的共享内存 (`/dev/shm`) 大小 |
| `GPU_MEMORY_UTILIZATION_SIZE` | `16gb`（如 `8gb`, `16gb`）；vLLM 推理引擎显存配额，系统自动结合总显存换算为 `gpu_memory_utilization` 比例传给 vLLM |
| `MINERU_API_URL` | `http://mineru_worker:8000`；宿主机运行网关需单独提供可访问的 Worker 地址 |
| `DOCKER_HOST` | Docker SDK 连接配置；示例：`unix:///var/run/docker.sock` |
| `IDLE_TIMEOUT_SECONDS` | `900`；监控每 10 秒检查一次 |
| `DEFAULT_MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS` | 容器启动等待超时（秒），默认 `300`；兼容旧变量 `WORKER_STARTUP_TIMEOUT_SECONDS` |
| `PARSE_BATCH_PAGES` | `1`；每个 PDF 检查点的页数 |
| `DEFAULT_MINERU_TASK_RESULT_TIMEOUT_SECONDS` | `3600`；每次批次轮询的超时秒数；每批最多尝试 3 次；兼容旧变量 `WORKER_TASK_TIMEOUT_SECONDS` |
| `SHARED_DATA_DIR` | `/usr/model/MinerU/data` |
| `MINERU_CONFIG_FILE` | `/usr/model/MinerU/mineru.json`；系统自动从 settings 生成 |
| `LOG_PATH`、`LOG_NAME`、`LOG_LEVEL` | 应用日志；相对路径基于仓库根目录解析；按天轮转，保留 14 份备份 |

解析选项通过 **multipart 表单字段**传入，不由环境变量设置默认值：

| 字段 | API 默认值 |
| --- | --- |
| `backend`、`effort`、`parse_method` | `hybrid-engine`、`medium`、`auto` |
| `formula_enable`、`table_enable` | `true` |
| `start_page_id`、`end_page_id` | `0`、`99999`（从 0 开始的页码索引） |
| `s` | 可选的恢复页码，等价于 `start_page_id`；默认自动恢复 |
| `force` | `false`（默认无需传）；传 `true` 时清理该同名文件的旧任务记录与检查点缓存，强制从第 0 页重新全量执行 GPU 识别 |

## 运维与 API 参考

> [!TIP]
> **交互式 API 文档 (Swagger UI)：** 网关服务启动后，可在浏览器中直接打开 [http://localhost:8080/docs](http://localhost:8080/docs) 查看完整的交互式 OpenAPI 文档与在线调试接口（或通过 [http://localhost:8080/openapi.json](http://localhost:8080/openapi.json) 获取原始定义）。

### GPU 容器生命周期控制

```bash
# 查看 Worker 容器状态与显存释放倒计时
curl --fail-with-body http://localhost:8080/api/v1/system/gpu/status

# 手动唤醒 Worker 容器并等待健康检查通过
curl --fail-with-body -X POST http://localhost:8080/api/v1/system/gpu/wake

# 停止 Worker 容器以彻底释放显存（若有活动任务则拒绝停止）
curl --fail-with-body -X POST http://localhost:8080/api/v1/system/gpu/sleep

# 强制停止 Worker 容器（即使有正在运行的任务，可能会中断解析）
curl --fail-with-body -X POST "http://localhost:8080/api/v1/system/gpu/sleep?force=true"

# 查看网关实时日志
sudo ./deploy/compose.sh logs --tail=100 sentry
```

### 完整 API 接口清单

| 请求方法与路径 | 接口摘要 | 功能描述 |
| --- | --- | --- |
| `POST /api/v1/parse` | 解析文档 | 上传、恢复或复用文档；解析完成后返回完整 Markdown 文本 |
| `POST /api/v1/parse/stream` | 流式解析 | 回放已落盘的 Markdown 前缀并实时按批次流式推送新结果 |
| `POST /api/v1/parse/by-filename/{filename}` | 按文件名获取/恢复 | 仅凭文件名恢复任务或直接读取已完成的完整 Markdown 结果 |
| `POST /api/v1/parse/resume` | 按任务 ID 恢复 | 传入任务 ID 显式恢复执行；返回完整 Markdown 文本 |
| `GET /api/v1/tasks/{task_id}` | 查询任务详情 | 查询任务状态、报错原因及各分片检查点列表 |
| `GET /api/v1/tasks/{task_id}/result` | 获取最终文本 | 直接返回已完成任务拼接后的完整 Markdown 文本 |
| `GET /api/v1/tasks/{task_id}/intermediate` | 获取中间结果 | 返回未完成任务当前已成功落盘的连续 Markdown 前缀 |
| `GET /api/v1/tasks/by-filename/{filename}` | 按文件名检索 | 查询匹配特定文件名的全部历史任务记录 |
| `GET /api/v1/tasks/by-hash/{file_hash}` | 按内容哈希检索 | 查询匹配文件 SHA-256 哈希的全部任务记录 |
| `GET /health` | 服务健康检查 | 基础网关状态检查与底层 Worker API 连通性测试 |
| `GET /api/v1/system/gpu/status` | Worker 状态监控 | 详细的 Worker 容器状态、活动任务数与显存释放倒计时 |
| `POST /api/v1/system/gpu/wake` | 手动拉起 Worker | 主动启动待机 Worker 容器并等待 `/health` 就绪 |
| `POST /api/v1/system/gpu/sleep` | 手动休眠 Worker | 停止 Worker 容器，彻底释放 RTX 5090 / 4090 显存 |

---

## 本地开发与测试

运行本地开发环境需 Python 3.12 以及 `pip`、`venv`：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r core/requirements.txt
cp -n core/config/.env.example core/config/.env.prod
```

根据本地环境配置数据库、Docker 套接字及存储目录，然后启动网关：

```bash
python core/main.py
```

### 无数据库模式启动 (Headless Gateway)
在尚未配置或启动 PostgreSQL 的情况下，可直接启动无数据库模式的网关：

```bash
POSTGRES_URL='' python core/main.py
```

在此模式下，文档解析相关接口不注册，但系统健康检查与 GPU 生命周期控制接口（`/health`、`/api/v1/system/gpu/*`）保持完全可用。

### 集成与检查点恢复测试
断点恢复与拼接逻辑测试位于 [tests/test_checkpoint_results.py](../../tests/test_checkpoint_results.py)，需配合独立 PostgreSQL 数据库执行：

```bash
SENTRY_TEST_DATABASE_URL=postgresql+psycopg2://mineru_admin:mineru_password@localhost:5432/mineru_sentry \
  python -m unittest discover -s tests -v
```

PostgreSQL 配置完成后，网关在启动时会自动进行数据库表迁移；归档 DDL 位于 [core/sql/2026-09-09.sql](../../core/sql/2026-09-09.sql)。

---

## 项目结构

- [core/main.py](../../core/main.py)：应用统一入口与 FastAPI 工厂。
- [core/api/](../../core/api/)：文档解析与系统 GPU 生命周期管理接口路由。
- [core/service/](../../core/service/)：Docker 容器编排、任务调度及 Markdown 结果拼接核心服务。
- [core/config/](../../core/config/)：配置加载器及系统环境模型定义。
- [deploy/](../../deploy/)：容器镜像构建文件、Compose 编排文件及部署运维脚本。
- [tests/](../../tests/)：检查点恢复与任务去重单元与集成测试套件。

---

## 开源许可证与致谢

本项目基于 [GNU 通用公共许可证 v3.0 (GPLv3)](../../LICENSE) 开源发布。

文档解析底层算法、布局分析模型及 OCR 引擎均来自上游优秀开源项目 [MinerU](https://github.com/opendatalab/MinerU)。模型与权重的许可条款请参阅其官方仓库说明。
