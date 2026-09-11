# MinerU-Sentry

English | [简体中文](docs/zh-CN/README-cn.md)

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker Compose](https://img.shields.io/badge/Docker_Compose-2.17+-2496ED.svg?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![MinerU Upstream](https://img.shields.io/badge/MinerU-Upstream-orange.svg)](https://github.com/opendatalab/MinerU)

**On-demand GPU standby gateway for self-hosted MinerU: receives document parsing requests over HTTP, records durable page-by-page checkpoints in PostgreSQL, streams raw Markdown, and stops the worker container when idle to reclaim RTX 5090 VRAM.**

[Quick Start](#quick-start) · [Core Highlights](#why-mineru-sentry) · [Parsing & Streams](#parsing--resumable-streams) · [Architecture & Lifecycle](#architecture--gpu-lifecycle) · [API Reference](#operations--api-reference) · [Configuration](#configuration)

---

### Real Terminal Evidence

#### 1. Zero-VRAM Standby Verification
When no tasks are running, the GPU worker container remains in `created` or `exited` status with **0 MB VRAM allocated**:

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

#### 2. Direct Markdown in HTTP Response Body
Submitting a document automatically wakes the worker, checkpoints every page, and returns clean Markdown text without requiring ZIP downloads or file decompression:

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

## Why MinerU-Sentry

- **Zero-VRAM Standby & On-Demand Lifecycle:** Sentry gateway and PostgreSQL run continuously with a minimal footprint (~50 MB RAM). When a parsing request arrives, Sentry dynamically wakes the pre-created GPU worker container; after 15 minutes of idle time (configurable via `IDLE_TIMEOUT_SECONDS`), Sentry automatically stops the container, completely freeing RTX 5090 / 4090 VRAM for local LLM inference or training.
- **Direct Markdown Delivery & Resumable Streams:** Standard endpoints return complete, stitched Markdown text directly in the HTTP body. Streaming endpoints (`POST /api/v1/parse/stream`) replay saved prefixes immediately and push new page batches as they finish. No ZIP archives, no download attachments, and no internal filesystem paths are exposed to callers.
- **Durable Page-by-Page Checkpoint Resumption:** PDF parsing defaults to 1 page per batch (`PARSE_BATCH_PAGES=1`). Each batch is atomically written to disk and committed to PostgreSQL before advancing. If an interruption, timeout, or container restart occurs, parsing resumes from the exact saved checkpoint without repeating expensive GPU neural OCR or layout analysis.
- **Automatic Task Deduplication & Reconnection:** Documents with matching filenames and SHA-256 content hashes automatically reuse existing tasks: completed tasks return cached results instantly; in-flight tasks attach to active execution; interrupted tasks resume from disk checkpoints.
- **Single-File Unified Configuration:** Gateway, GPU Worker, and Docker Compose are driven by a single environment file (`core/config/.env.prod`, customizable via `CONFIG_FILE_PATH`). MinerU's internal `/usr/model/MinerU/mineru.json` is generated dynamically on startup and worker wake—no manual config editing required.

> [!NOTE]
> **Scope & Boundaries:** A single gateway instance manages one dedicated GPU worker container on the host. PDF inputs support page-by-page checkpointing and resumption; other document formats are handled as whole units.

---

## Architecture & GPU Lifecycle

### System Data Flow

```mermaid
flowchart LR
    Client[Client HTTP Request] --> Sentry[Sentry HTTP Gateway]
    Sentry --> DB[(PostgreSQL Tasks & Checkpoints)]
    Sentry -->|Wake On-Demand| Worker[MinerU GPU Worker Container]
    Worker -->|Batch Markdown Output| Sentry
    Sentry --> Files[Durable Page Checkpoints & Stitched Output]
    Sentry -->|Direct Markdown / Chunked Stream| Client
    Sentry -.->|Idle Timeout: 15m Auto-Stop| Worker
```

### Worker Container Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> Standby: compose.sh init / create (0 MB VRAM)
    Standby --> Waking: Parse Request (POST /api/v1/parse)
    Standby --> Waking: Manual Wake (POST /api/v1/system/gpu/wake)
    Waking --> Active: Worker Health Check Passed (/health 200 OK)
    Active --> Active: Process Page Batches & Commit Checkpoints
    Active --> IdleCountdown: All Active Tasks Completed
    IdleCountdown --> Active: New Parse Task Arrives (Timer Reset)
    IdleCountdown --> Standby: Idle Timeout Reached (default 900s) -> docker stop (0 MB VRAM)
    Active --> Standby: Manual Sleep (POST /api/v1/system/gpu/sleep)
```

Compose does not assign GPU resources to the Sentry gateway itself; all neural inference is strictly isolated within the GPU worker container.

---

## Quick Start

Run the following commands in the repository root on an RTX 5090 Linux host. Requires a compatible NVIDIA driver, Docker Engine, NVIDIA Container Toolkit, Compose 2.17+, and BuildKit. MinerU is built from local source at `${MINERU_SOURCE_DIR}`; models, caches, and parsed outputs reside under `/usr/model/MinerU`.

### 1. Configure Environment (Single Unified File)

All configuration is consolidated in a single environment file (defaults to `core/config/.env.prod`, override via `CONFIG_FILE_PATH`):

```bash
# Copy template and edit configuration
cp core/config/.env.example core/config/.env.prod
$EDITOR core/config/.env.prod
```

- **Unified configuration:** Gateway, GPU Worker, and Docker Compose read from the same `.env` file and `settings.py`.
- **Automatic `mineru.json` generation:** The gateway automatically generates `/usr/model/MinerU/mineru.json` from settings on startup and container wake; manual configuration is never required.
- **Flexible PostgreSQL connection:** Sentry only connects to PostgreSQL and does not bundle database lifecycle. Use an existing database, host service, or external container. To quickly run a dedicated PostgreSQL container via Docker:
  ```bash
  ./docs/deploy/postgres.sh
  ```

### 2. Deploy & Launch

#### Option A: One-Click Initial Setup (Recommended)
Builds images, downloads models, creates the standby worker container, and starts the gateway:
```bash
./docs/deploy/compose.sh init
```

#### Option B: Step-by-Step
```bash
# 1. Build images
./docs/deploy/compose.sh build sentry mineru_worker

# 2. Download models (skip if models already exist locally)
./docs/deploy/compose.sh download

# 3. Create standby worker container and start gateway
./docs/deploy/compose.sh create mineru_worker
./docs/deploy/compose.sh up -d sentry
```

For daily restarts or launches:
```bash
./docs/deploy/compose.sh start
```

Verify service and worker status:
```bash
./docs/deploy/compose.sh --profile worker ps -a
curl --fail-with-body http://localhost:8080/health
```

- **Standby worker behavior:** Sentry wakes the worker container on demand. The worker uses the Compose `worker` profile and remains `exited` during idle periods, ensuring zero VRAM usage.
- Only port `8080` on the gateway is published; gateway and worker communicate via internal Docker networks.

---

## Parsing & Resumable Streams

Uploading a document with the same filename, content hash, and options will automatically connect to or resume the matching task. If options or page ranges conflict with an existing task under the same name, HTTP 409 is returned to protect consistency.

### 1. Return Complete Markdown

```bash
curl --fail-with-body http://localhost:8080/api/v1/parse   -F 'file=@document.pdf'   -F 'backend=hybrid-engine'   -F 'effort=medium'
```

Completed tasks immediately return the full Markdown content. Incomplete tasks continue execution and return the stitched document upon completion. The task ID is provided in the `X-Sentry-Task-ID` response header for diagnostics.

### 2. Chunked Streaming by Batch

```bash
curl -N --fail-with-body http://localhost:8080/api/v1/parse/stream   -F 'file=@document.pdf'
```

Replays the already-saved Markdown prefix, then flushes new batches as they finish parsing. Every reconnect streams from the beginning of the document, so callers should replace partial buffers rather than appending.

Client disconnections do not abort the background parsing task. Failed batches are retried up to 3 times before failing the task.

### 3. Explicit Resume Offset

If pages 0 through 208 have already been committed, resume parsing starting from page index 209 (page 210):

```bash
curl --fail-with-body http://localhost:8080/api/v1/parse   -F 'file=@document.pdf'   -F 's=209'
```

Also accepts `start_page_id=209` as a form field or query parameter. Unfinished tasks automatically resume without specifying `s`. Supplying an offset that skips uncommitted pages returns HTTP 409.

### 4. Fetch or Resume by Filename

Fetch completed results or resume an existing upload using only its filename:

```bash
curl --fail-with-body -X POST http://localhost:8080/api/v1/parse/by-filename/document.pdf
```

---

## Configuration

All configuration items are managed via a single configuration file (default `core/config/.env.prod`, template in [core/config/.env.example](core/config/.env.example)):

| Variable | Default / Description |
| --- | --- |
| `SERVICE_PORT`, `SENTRY_HOST` | `8080`, `0.0.0.0` |
| `POSTGRES_URL` | PostgreSQL hostname or full SQLAlchemy URL; parsing routes disabled if unset |
| `POSTGRES_PORT` | `5432`; requires `POSTGRES_DATABASE`, `POSTGRES_USERNAME`, `POSTGRES_PASSWORD` if URL is a hostname |
| `MINERU_IMAGE_TYPE` | `local` (build from local MinerU source, recommended) or `docker` (pull from custom/private registry) |
| `MINERU_IMAGE_LOCAL` | `mineru-api:5090-source`; image name and tag for local source build mode |
| `MINERU_IMAGE_DOCKER` | `alexsuntop/mineru:3.4.2`; remote prebuilt image or custom private registry when `MINERU_IMAGE_TYPE=docker` |
| `MINERU_WORKER_CONTAINER_NAME` | `mineru_gpu_worker` |
| `MINERU_SHM_SIZE` | `16gb`; shared memory size (`/dev/shm`) allocated to the GPU worker container |
| `GPU_MEMORY_UTILIZATION_SIZE` | `16gb` (e.g. `8gb`, `16gb`); target vLLM GPU memory size; dynamically converts to `gpu_memory_utilization` ratio passed to vLLM |
| `MINERU_API_URL` | `http://mineru_worker:8000`; worker endpoint accessible by the gateway |
| `DOCKER_HOST` | Docker socket path; defaults to `unix:///var/run/docker.sock` |
| `IDLE_TIMEOUT_SECONDS` | `900`; idle countdown threshold; checked by monitor loop every 10 seconds |
| `DEFAULT_MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS` | `300`; timeout in seconds waiting for worker `/health` readiness |
| `PARSE_BATCH_PAGES` | `1`; pages per checkpoint segment; 1 is recommended for granular resume |
| `DEFAULT_MINERU_TASK_RESULT_TIMEOUT_SECONDS` | `3600`; per-batch polling timeout; retried up to 3 times |
| `SHARED_DATA_DIR` | `/usr/model/MinerU/data`; shared volume between host and containers |
| `MINERU_CONFIG_FILE` | `/usr/model/MinerU/mineru.json`; automatically generated from settings |
| `LOG_PATH`, `LOG_NAME`, `LOG_LEVEL` | Application logging paths; daily rotation with 14 retained backups |

Parsing options are passed as **multipart form fields** per request:

| Field | API Default | Description |
| --- | --- | --- |
| `backend`, `effort`, `parse_method` | `hybrid-engine`, `medium`, `auto` | Parsing engine and strategy |
| `formula_enable`, `table_enable` | `true`, `true` | Formula detection and table extraction |
| `start_page_id`, `end_page_id` | `0`, `99999` | Zero-indexed page range |
| `s` | None (auto-detect) | Explicit resume offset, equivalent to `start_page_id` |
| `force` | `false` | When `true`, cleans existing task records/checkpoints for this filename and forces fresh GPU re-parsing from page 0 |

---

## Operations & API Reference

> [!TIP]
> **Interactive API Documentation (Swagger UI):** When the gateway is running, access full interactive OpenAPI schemas and API testing directly in your browser at [http://localhost:8080/docs](http://localhost:8080/docs) (or retrieve raw JSON at [http://localhost:8080/openapi.json](http://localhost:8080/openapi.json)).

### GPU Lifecycle Control

```bash
# Check worker status and idle countdown
curl --fail-with-body http://localhost:8080/api/v1/system/gpu/status

# Wake worker container and await readiness
curl --fail-with-body -X POST http://localhost:8080/api/v1/system/gpu/wake

# Stop worker to free VRAM (rejected if active tasks are running)
curl --fail-with-body -X POST http://localhost:8080/api/v1/system/gpu/sleep

# Force stop worker even when tasks are active (may interrupt running jobs)
curl --fail-with-body -X POST "http://localhost:8080/api/v1/system/gpu/sleep?force=true"

# View gateway logs
sudo ./docs/deploy/compose.sh logs --tail=100 sentry
```

### Complete Endpoint Directory

| Method & Path | Summary | Description |
| --- | --- | --- |
| `POST /api/v1/parse` | Parse Document | Upload, resume, or reuse document; returns complete Markdown |
| `POST /api/v1/parse/stream` | Stream Document | Replay saved prefix and stream live batch results |
| `POST /api/v1/parse/by-filename/{filename}` | Resume by Filename | Resume or fetch result by filename; returns complete Markdown |
| `POST /api/v1/parse/resume` | Resume by Task ID | Resume execution by task ID; returns complete Markdown |
| `GET /api/v1/tasks/{task_id}` | Query Task Details | Query task details, error status, and segment checkpoints |
| `GET /api/v1/tasks/{task_id}/result` | Fetch Result | Return complete Markdown text for a finished task |
| `GET /api/v1/tasks/{task_id}/intermediate` | Fetch Intermediate Text | Return contiguous saved Markdown prefix for an incomplete task |
| `GET /api/v1/tasks/by-filename/{filename}` | Find by Filename | Find task records matching exact filename |
| `GET /api/v1/tasks/by-hash/{file_hash}` | Find by Content Hash | Find task records matching file SHA-256 |
| `GET /health` | Health Check | Basic gateway health check and worker API connectivity |
| `GET /api/v1/system/gpu/status` | Worker Status | Detailed container state, active task count, and idle countdown |
| `POST /api/v1/system/gpu/wake` | Wake Worker | Manually wake GPU worker container |
| `POST /api/v1/system/gpu/sleep` | Sleep Worker | Manually sleep GPU worker container to release VRAM |

---

## Local Development & Testing

Requires Python 3.12 with `pip` and `venv`:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r core/requirements.txt
cp -n core/config/.env.example core/config/.env.prod
```

Configure your local database, Docker socket, and storage paths in `core/config/.env.prod`, then launch:

```bash
python core/main.py
```

### Running Headless Gateway (Without Database)
If PostgreSQL is not yet configured, launch a headless gateway instance:

```bash
POSTGRES_URL='' python core/main.py
```

In this mode, parsing endpoints are disabled, but system health checks and GPU lifecycle controls (`/health`, `/api/v1/system/gpu/*`) remain fully functional.

### Integration & Checkpoint Tests
Checkpoint recovery and result stitching tests are located at [tests/test_checkpoint_results.py](tests/test_checkpoint_results.py), utilizing an isolated database and real disk files:

```bash
SENTRY_TEST_DATABASE_URL=postgresql+psycopg2://mineru_admin:mineru_password@localhost:5432/mineru_sentry \
  python -m unittest discover -s tests -v
```

Database schema migrations are automatically executed on startup when PostgreSQL is configured. Archived DDL is available at [core/sql/2026-09-09.sql](core/sql/2026-09-09.sql).

---

## Project Structure

- [core/main.py](core/main.py): Application entry point and FastAPI factory.
- [core/api/](core/api/): HTTP route definitions for document parsing and GPU lifecycle control.
- [core/service/](core/service/): Business logic for Docker container orchestration, task scheduling, and markdown stitching.
- [core/config/](core/config/): Configuration loader and settings models.
- [docs/deploy/](docs/deploy/): Dockerfiles, Docker Compose orchestrations, and deployment shell scripts.
- [tests/](tests/): Unit and integration test suite for checkpoint recovery and deduplication.

---

## License & Attribution

This project is licensed under the [GNU General Public License v3.0 (GPLv3)](LICENSE).

Document parsing algorithms, layout models, and OCR backends are provided by [MinerU](https://github.com/opendatalab/MinerU). Please consult upstream repositories for model licensing and third-party terms.
