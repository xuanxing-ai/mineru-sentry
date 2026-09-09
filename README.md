# MinerU-Sentry

English | [简体中文](docs/zh-CN/README-cn.md)

**An on-demand GPU gateway for self-hosted MinerU: accept document parsing jobs over HTTP, keep task records in PostgreSQL, and stop the worker when it is idle.**

[Quick start](#quick-start) · [Parse a document](#parse-a-document) · [Configuration](#configuration) · [MinerU upstream](https://github.com/opendatalab/MinerU)

```mermaid
flowchart LR
    Client[Client Request] --> Sentry[Sentry HTTP API]
    Sentry --> DB[(PostgreSQL Task & Checkpoint Records)]
    Sentry -->|Start on demand| Worker[MinerU GPU Worker]
    Worker -->|Batch Markdown Results| Sentry
    Sentry --> Files[Disk Checkpoints & Stitched Result]
    Sentry -->|Direct Markdown / Streaming Output| Client
    Sentry -.->|Stop after 15 idle minutes| Worker
```

The gateway has no GPU allocation in Compose. Only the worker runs inference; Sentry starts an **existing container**, waits for its API, and stops it after a configurable idle period.

## Why Sentry

- **Direct Markdown results without ZIP archives or download links.** Complete Markdown text is returned directly in the HTTP response body; no ZIP files or intermediate download redirects.
- **Dedicated streaming and checkpoint persistence endpoint.** `/api/v1/parse/stream` persists each completed batch to disk as a checkpoint while simultaneously streaming text chunks to the client. Intermediate checkpoints are safely preserved on disk.
- **Seamless breakpoint reconnection (automatic resume & stitching).** When uploading a same-name file:
  - **Completed documents**: directly output the full result without re-parsing.
  - **Unfinished / interrupted documents**: automatically resumes from the last completed checkpoint, finishes remaining pages, and stitches earlier batches (e.g. `0_208.md`) and resumed batches (e.g. `209_end.md`) together into the complete Markdown result. No external glue scripts needed.
- **Native `-s` offset support.** Pass `-F s=209` or `?s=209` to specify an explicit resume page; Sentry automatically stitches previously completed batches before page 209 with the resumed remainder and outputs the unified Markdown result.
- **Intelligent GPU scale-to-zero.** GPU worker is stopped automatically when idle, releasing VRAM, and woken on demand.

**Current scope:** one gateway process managing one GPU worker. The supplied worker recipe targets RTX 5090; this repository does not include hardware benchmarks or an end-to-end GPU test suite.

## Quick start

Run commands from the repository root. Full parsing requires Docker Engine with Compose, a Linux NVIDIA GPU host with a compatible driver and NVIDIA Container Toolkit, and locally downloaded MinerU models. The gateway image uses Python 3.12; Compose supplies PostgreSQL 16.

### 1. Prepare local models

```bash
sudo mkdir -p /usr/model/MinerU/pipeline /usr/model/MinerU/vlm /usr/model/MinerU/data
sudo cp -n core/config/mineru.template.json /usr/model/MinerU/mineru.json
```

Download models for your installed MinerU version using its [local-model instructions](https://opendatalab.github.io/MinerU/usage/model_source/). Place pipeline and VLM model files in the directories above, or edit `models-dir` in `/usr/model/MinerU/mineru.json` to match their locations **inside the worker container**. Empty directories and the JSON template are not enough to parse documents.

Both containers mount `/usr/model/MinerU` at the same path. Keep models and configuration readable and the `data` directory writable by the containers.

### 2. Build and create the worker, then start the gateway

The [Compose file](deploy/docker-compose.yml) includes example database credentials, published ports `8080`, `8000`, and `5432`, and a Docker socket mount for Sentry. Use it on a trusted host; configure credentials and network access before exposing it. The API has no built-in authentication, including GPU control endpoints.

```bash
docker compose -f deploy/docker-compose.yml build sentry mineru_worker
docker compose -f deploy/docker-compose.yml create mineru_worker
docker compose -f deploy/docker-compose.yml up -d sentry postgres
curl --fail-with-body http://localhost:8080/health
```

**Do not skip `create mineru_worker`.** Sentry can start and stop the named container, but cannot create it. The worker stays stopped until a parsing request or manual wake. Its status is normally `created` before the first start and `exited` after a stop.

Open [Swagger UI](http://localhost:8080/docs) for the API schema. `/health` reports Docker worker state, not database readiness. `mineru_api_healthy=false` is expected while the worker is stopped; `is_gpu_active` reflects container state rather than measured GPU utilization.

The [worker Dockerfile](deploy/worker.Dockerfile) uses a mirror of `vllm/vllm-openai:v0.21.0` and installs `mineru[core]>=3.4.0`. Dependencies are not fully pinned; validate the resolved MinerU API and GPU runtime on your host. Startup waits up to 300 seconds by default, with no fixed cold-start guarantee.

## Parse documents and breakpoint reconnection

Provide a local document (such as `document.pdf`). Supported file formats depend on the installed MinerU worker.

### 1. Standard parsing (direct Markdown result)

```bash
curl --fail-with-body http://localhost:8080/api/v1/parse \
  -F 'file=@document.pdf'
```

- **Completed document**: directly returns the full Markdown text (no ZIP, no file downloads).
- **Unfinished or interrupted document**: seamlessly continues from the breakpoint to completion and returns the complete stitched result.

### 2. Streaming parse and streaming disk write (dedicated endpoint)

For large documents, use the streaming endpoint to write checkpoints to disk while streaming text chunks to the client:

```bash
curl -N --fail-with-body http://localhost:8080/api/v1/parse/stream \
  -F 'file=@document.pdf'
```

- Each batch is persisted to disk as `checkpoints/{start}_{end}.md` upon completion (streaming disk write).
- Chunks are yielded immediately to the HTTP client (streaming output).
- If interrupted, completed batches remain intact on disk.

### 3. Breakpoint reconnection with `-s` offset

When a large document parsing is interrupted (e.g. at page 210):
- Pages 0 to 208 remain saved as durable checkpoints (e.g. `0_208.md`).
- **Auto-resume**: re-submit the same file; Sentry automatically detects the checkpoint and continues from page 209:
  ```bash
  curl --fail-with-body http://localhost:8080/api/v1/parse \
    -F 'file=@document.pdf'
  ```
- **Resume with `-s`**: explicitly specify the starting page:
  ```bash
  curl --fail-with-body http://localhost:8080/api/v1/parse \
    -F 'file=@document.pdf' \
    -F 's=209'
  ```
  Sentry automatically stitches `0_208.md` and the resumed `209_end.md` together inside the service and returns the complete Markdown. No external glue script required.

## Configuration

For local execution, copy [env.example](core/config/env.example) to `core/config/.env.dev`. Process environment variables take precedence. `CONFIG_FILE_PATH=.env.prod` selects `core/config/.env.prod`; absolute paths are also supported. Compose passes its own environment and does not load this file automatically.

| Setting | Default or behavior |
| --- | --- |
| `SERVICE_PORT`, `SENTRY_HOST` | `8080`, `0.0.0.0`; `SERVICE_PORT` takes precedence over legacy `SENTRY_PORT` |
| `POSTGRES_URL` | Database hostname or full SQLAlchemy URL; unset disables parsing routes |
| `POSTGRES_PORT` | `5432`; with a hostname, also set `POSTGRES_DATABASE`, `POSTGRES_USERNAME`, and `POSTGRES_PASSWORD` |
| `MINERU_WORKER_CONTAINER_NAME` | `mineru_gpu_worker` |
| `MINERU_API_URL` | `http://mineru_worker:8000`; use `http://127.0.0.1:8000` for a host-run gateway with the published worker port |
| `DOCKER_HOST` | Docker SDK connection; example: `unix:///var/run/docker.sock` |
| `IDLE_TIMEOUT_SECONDS` | `900`; the monitor checks every 10 seconds |
| `WORKER_STARTUP_TIMEOUT_SECONDS` | `300` |
| `SHARED_DATA_DIR` | `/usr/model/MinerU/data` |
| `LOG_PATH`, `LOG_NAME`, `LOG_LEVEL` | Application logs; relative paths resolve from the repository root; daily rotation retains 14 backups |

Parsing options are **multipart form fields**, not environment defaults:

| Field | API default |
| --- | --- |
| `backend`, `effort`, `parse_method` | `hybrid-engine`, `medium`, `auto` |
| `formula_enable`, `table_enable` | `true` |
| `start_page_id`, `end_page_id` | `0`, `99999` (zero-based page indices) |
| `auto_resume` | `true` |

The `DEFAULT_*` entries and `HOST_MINERU_DIR` in `env.example` are not consumed by the current gateway. `MINERU_CONFIG_FILE` does not configure the worker; the worker reads `MINERU_TOOLS_CONFIG_JSON`, set in Compose. Compose also sets `MINERU_MODEL_SOURCE=local` and `MINERU_PROCESSING_WINDOW_SIZE=64`; the latter is a worker setting, not a gateway memory guarantee.

## Operations and API reference

```bash
# Inspect the worker and idle countdown.
curl --fail-with-body http://localhost:8080/api/v1/system/gpu/status

# Start the worker and wait for its health endpoint.
curl --fail-with-body -X POST http://localhost:8080/api/v1/system/gpu/wake

# Stop the worker; rejected while Sentry has active tasks.
curl --fail-with-body -X POST http://localhost:8080/api/v1/system/gpu/sleep

# Inspect service logs.
docker compose -f deploy/docker-compose.yml logs --tail=100 sentry mineru_worker
```

`POST /api/v1/system/gpu/sleep?force=true` also stops a worker with active jobs and can interrupt them. Idle tracking only covers jobs submitted through this gateway; direct worker requests are not counted.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/parse` | Upload and submit a document |
| `POST /api/v1/parse/resume` | Create a resumed task |
| `GET /api/v1/tasks/{task_id}` | Task details, errors, and segments |
| `GET /api/v1/tasks/{task_id}/result` | Download completed Markdown |
| `GET /api/v1/tasks/{task_id}/intermediate` | List available files and preview Markdown |
| `GET /api/v1/tasks/by-filename/{filename}` | Find records by filename |
| `GET /api/v1/tasks/by-hash/{file_hash}` | Find records by SHA-256 |
| `GET /health`, `GET /api/v1/system/gpu/status` | Worker state and idle countdown |
| `POST /api/v1/system/gpu/wake`, `POST /api/v1/system/gpu/sleep` | Manual worker lifecycle control |

Task records persist, but execution threads and active-task counters are in memory. Run a single gateway process: there is no durable job queue, automatic restart recovery, or cross-process scheduler coordination. Worker status polling retries without an overall deadline, so an unreachable worker can leave a task active until intervention.

Uploads are read into gateway memory. Set appropriate upload limits at your ingress and manage storage retention outside the application. Stopping the worker ends its GPU processes; Sentry does not measure freed VRAM or memory used by other applications.

## Local development

Use Python 3.12 with `pip` and `venv` available. On Debian/Ubuntu, the latter may require the `python3-venv` package.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp -n core/config/env.example core/config/.env.dev
```

Edit the database settings, Docker connection, shared directory, and worker URL for your host, then run:

```bash
python main.py
```

To inspect the system API without PostgreSQL, start the gateway with:

```bash
POSTGRES_URL='' python main.py
```

In another terminal, fetch the schema or open [Swagger UI](http://localhost:8080/docs):

```bash
curl --fail-with-body http://localhost:8080/openapi.json
```

In this mode, parsing routes are absent; `/health` and GPU operations still require Docker access. With PostgreSQL configured, startup attempts to create tables; the archived schema is [core/sql/2026-09-09.sql](core/sql/2026-09-09.sql).

## Project and support

[main.py](main.py) is the application entry point. [core/](core/) contains the API, services, persistence, and configuration; [deploy/](deploy/) contains the container recipes and Compose stack.

For bug reports, include the failing endpoint, task status/error, resolved MinerU version, relevant logs, and deployment details with credentials removed. There is no checked-in automated test suite; worker integration changes need validation against a running MinerU service.

Parsing is provided by [MinerU](https://github.com/opendatalab/MinerU). This repository currently contains no license file; consult the maintainers for its licensing terms and upstream projects for their respective licenses.
