# ==============================================================================
# MinerU-Sentry: Lightweight Standby Gateway (Zero VRAM, 24/7 Available)
# Conforming to code-backend-python-style
# ==============================================================================

FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install python dependencies using Tsinghua PyPI mirror
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared infrastructure and the business package
COPY main.py /app/main.py
COPY core/ /app/core/

# Expose HTTP port
EXPOSE 8080

# Run FastAPI app with Uvicorn
CMD ["python", "main.py"]
