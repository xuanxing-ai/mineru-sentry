# syntax=docker/dockerfile:1
ARG MINERU_BASE_IMAGE=vllm/vllm-openai:v0.21.0

# Build the MinerU distribution from the separate local source checkout.
FROM python:3.12-slim AS mineru-build
WORKDIR /opt/mineru-source
COPY --from=mineru_source pyproject.toml README.md LICENSE.md ./
COPY --from=mineru_source mineru/ ./mineru/
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir /opt/wheels .

# CUDA / PyTorch / vLLM are supplied by the upstream GPU runtime image.
FROM ${MINERU_BASE_IMAGE}
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fonts-noto-core fonts-noto-cjk fontconfig libgl1 && \
    fc-cache -f && \
    rm -rf /var/lib/apt/lists/*

COPY --from=mineru-build /opt/wheels/ /tmp/mineru-wheel/
# Install the locally built wheel plus API inference dependencies, without the UI extra.
RUN set -- /tmp/mineru-wheel/mineru-*.whl && \
    python3 -m pip install --no-cache-dir --break-system-packages "$1[pipeline,vlm]" && \
    rm -rf /tmp/mineru-wheel

WORKDIR /usr/model/MinerU
CMD ["mineru-api", "--host", "0.0.0.0", "--port", "8000"]
