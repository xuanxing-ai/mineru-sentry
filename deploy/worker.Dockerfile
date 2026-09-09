# ==============================================================================
# MinerU GPU Worker Dockerfile for NVIDIA RTX 5090 (Blackwell Architecture)
# Base image supports Compute Capability 7.0 - 12.1 (Volta, Turing, Ampere, Ada, Hopper, Blackwell)
# Note: Model weights are NOT bundled in the image; mounted via /usr/model/MinerU
# ==============================================================================

# China mirror of vllm-openai image (supports CUDA 13.0 & Blackwell sm_120)
FROM docker.m.daocloud.io/vllm/vllm-openai:v0.21.0
# Global / official alternative:
# FROM vllm/vllm-openai:v0.21.0

# Install OpenCV dependencies & CJK fonts for rendering
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fonts-noto-core \
        fonts-noto-cjk \
        fontconfig \
        libgl1 \
        curl && \
    fc-cache -fv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install MinerU core package with pip
RUN python3 -m pip install -U 'mineru[core]>=3.4.0' \
        -i https://mirrors.aliyun.com/pypi/simple \
        --break-system-packages && \
    python3 -m pip cache purge

# Working directory
WORKDIR /workspace

# Entrypoint preserves arguments
ENTRYPOINT ["/bin/bash", "-c", "exec \"$@\"", "--"]

# Default command: launch mineru-api on port 8000
CMD ["mineru-api", "--host", "0.0.0.0", "--port", "8000"]
