# Multi-stage build. CPU base by default so the API and behaviour layers can be deployed on
# hardware that has no GPU; the perception worker adds CUDA on top of the same image.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM base AS builder
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --prefix=/install .

FROM base AS api
COPY --from=builder /install /usr/local
COPY configs ./configs
COPY sql ./sql

# Never run as root: this container is reachable from the caregiver network.
RUN useradd --create-home --uid 10001 wellbeing
USER wellbeing

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/v1/health || exit 1

CMD ["uvicorn", "wellbeing.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
