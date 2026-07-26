# VoidSwitch backend image.
#
# Built from the REPOSITORY ROOT (not backend/) on purpose: the gateway's
# /install endpoint serves the OpenCode plugin from <repo-root>/opencode-plugin/
# src/index.ts (parents[3] of voidswitch/api/install.py). Both the backend and
# that plugin source must live in the image at their original relative layout, so
# /install → /opencode/voidswitch.ts keeps working in the container.
#
#   docker build -t voidswitch .
#
# Layout inside the image mirrors the repo:
#   /app/backend          ← the gateway (venv at /app/backend/.venv)
#   /app/opencode-plugin  ← plugin source served by /opencode/voidswitch.ts

# ---- builder: resolve and install dependencies into a self-contained venv ----
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

# Dependencies install from PyPI by default. To build behind a package mirror,
# pass one at build time (empty = default PyPI):
#   docker build --build-arg UV_INDEX_URL=https://<your-mirror>/pypi/simple/ .
ARG UV_INDEX_URL=""
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_INDEX_URL=${UV_INDEX_URL}

WORKDIR /app/backend

# Install deps first (cached) without the project for a warm layer, then the
# project itself. --no-dev keeps test/lint tooling out of the image.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

COPY backend/ /app/backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- runtime: slim image carrying only the venv + source ----
FROM python:3.13-slim-bookworm

# Run as an unprivileged user; give it an owned data dir for the SQLite DB and
# .secret_key.
RUN useradd --create-home --uid 10001 voidswitch \
    && mkdir -p /data \
    && chown voidswitch:voidswitch /data

WORKDIR /app/backend
COPY --from=builder --chown=voidswitch:voidswitch /app/backend /app/backend

# OpenCode plugin source — served verbatim by /opencode/voidswitch.ts (the
# /install script downloads it). install.py resolves it at
# <repo-root>/opencode-plugin/src/index.ts → /app/opencode-plugin/src/index.ts.
# Only src is needed: the plugin's lone import is type-only and erased at load.
COPY --chown=voidswitch:voidswitch opencode-plugin/src /app/opencode-plugin/src

# Put the venv on PATH so `voidswitch` resolves without `uv run`.
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    # Default the DB onto the /data volume so it survives container recreation.
    # Override for Postgres etc. via VOIDSWITCH_DATABASE__URL.
    VOIDSWITCH_DATABASE__URL="sqlite+aiosqlite:////data/voidswitch.db"

USER voidswitch

EXPOSE 8080

# No config.yaml is baked in (it holds secrets and is gitignored). Supply
# configuration via VOIDSWITCH_* env vars, or mount one and set VOIDSWITCH_CONFIG.
# For stable dashboard sessions across container recreation, set a fixed
# VOIDSWITCH_SERVER__SECRET_KEY (otherwise one is auto-generated per container).
CMD ["voidswitch"]
