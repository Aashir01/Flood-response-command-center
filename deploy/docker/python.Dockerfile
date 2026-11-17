# syntax=docker/dockerfile:1.7
# One Dockerfile for every Python service (organs and Brain), deploy design 4.1.
#   docker build -f deploy/docker/python.Dockerfile --build-arg PACKAGE=stitch-ledger \
#     --build-arg SRC_DIR=organs/ledger --target runtime .
#   ... --build-arg PACKAGE=stitch-library --build-arg SRC_DIR=organs/library --target library .
# The image keeps the repository layout under /app (editable workspace install), so every
# repo-relative data path the organs use in development (data/demo, organs/<x>/models) resolves
# the same way in the container. CPU-only wheels, no dev or training dependencies, uid 10001.

ARG PYTHON_IMAGE=python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8

# Workspace manifests only (every pyproject.toml plus uv.lock): the dependency layer below is
# rebuilt only when a manifest or the lock changes, not on every source edit.
FROM base AS manifests
COPY . /src
RUN find /src -type f ! -name pyproject.toml ! -name uv.lock -delete \
 && find /src -depth -type d -empty -delete

FROM base AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
ARG PACKAGE
ARG SRC_DIR
RUN test -n "$PACKAGE" && test -n "$SRC_DIR"
COPY --from=manifests /src/ /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-default-groups --no-install-workspace --package "$PACKAGE"
COPY packages/ /app/packages/
COPY ${SRC_DIR}/ /app/${SRC_DIR}/
COPY data/demo/ /app/data/demo/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-default-groups --package "$PACKAGE" \
 && python -m compileall -q -j 0 /app/packages /app/${SRC_DIR} \
 && ! python -c "import torch" 2>/dev/null
# Drop bundled test suites and C headers of third-party wheels (not used at runtime).
RUN site=/app/.venv/lib/python3.12/site-packages \
 && find "$site" -depth -type d \( -name tests -o -name testing_data \) -path "$site/*/*" -exec rm -rf {} + \
 && rm -rf "$site/pyarrow/include" "$site/numpy/_core/include" \
 && find "$site" -type f \( -name '*.pyx' -o -name '*.pxd' -o -name '*.h' \) -delete

# Library models (embedder e5-small int8, reranker mMiniLM uint8): fetched at build time from
# pinned Hugging Face revisions with sha256 checks, then the int8 export with its parity check.
# Nothing downloads at runtime. `localmodels` can be replaced by an already fetched directory
# (compose: STITCH_MODELS_CONTEXT=data/raw/models) to skip the download.
FROM scratch AS localmodels

FROM build AS library-models
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-default-groups --package stitch-library --extra export
COPY scripts/fetch_models.py scripts/export_models.py /app/scripts/
COPY --from=localmodels / /models-seed/
RUN --mount=type=cache,id=stitch-library-models,target=/cache \
    set -eu; \
    cp -an /models-seed/. /cache/ 2>/dev/null || true; \
    python /app/scripts/fetch_models.py --dir /cache; \
    if [ ! -s /cache/e5-small/model_int8.onnx ] || [ ! -s /cache/e5-small/export_report.json ]; then \
        python /app/scripts/export_models.py --dir /cache; \
    fi; \
    mkdir -p /models; \
    for m in e5-small mmarco; do \
        mkdir -p "/models/$m"; \
        for f in model_int8.onnx tokenizer.json config.json REVISION export_report.json; do \
            if [ -f "/cache/$m/$f" ]; then cp "/cache/$m/$f" "/models/$m/$f"; fi; \
        done; \
    done; \
    test -s /models/e5-small/model_int8.onnx || cp /cache/e5-small/model_fp32.onnx /models/e5-small/; \
    ls -la /models/*

FROM base AS runtime
# libgomp1: OpenMP runtime needed by LightGBM (Oracle) and harmless elsewhere (~300 KB).
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin app \
 && groupadd --gid 10002 seed \
 && useradd --uid 10002 --gid 10002 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin seed
COPY --from=build /app /app
ENV PATH=/app/.venv/bin:$PATH \
    HOME=/tmp \
    STITCH_HOST=0.0.0.0 \
    STITCH_PORT=8000 \
    STITCH_MODE=demo \
    STITCH_LLM_PROVIDER=fake \
    OMP_NUM_THREADS=2
WORKDIR /app
ARG PACKAGE
ARG SRC_DIR
ARG SOURCE_URL=""
LABEL org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.licenses="MIT" \
      dev.stitch.package="${PACKAGE}"
USER 10001:10001
EXPOSE 8000
# The service command is set per service in compose.yaml.
CMD ["python", "-c", "print('set the command in compose.yaml')"]

FROM runtime AS library
COPY --from=library-models /models /app/models
COPY deploy/docker/library_seed.py /app/deploy/library_seed.py
ENV STITCH_MODEL_DIR=/app/models
