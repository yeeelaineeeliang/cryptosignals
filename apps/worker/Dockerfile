# syntax=docker/dockerfile:1
#
# Crypto Signals worker — Python 3.12 + uv.
# Uses uv for reproducible installs from uv.lock; total image ~180MB.

FROM python:3.12-slim

# uv for fast, deterministic installs
RUN pip install --no-cache-dir uv==0.5.*

WORKDIR /app

# Lockfile + metadata first for best layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies into .venv (no dev deps, fully frozen to lockfile)
RUN uv sync --frozen --no-dev

# Source code
COPY worker ./worker

# Put the venv on PATH and skip uv on runtime
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "worker.main"]
